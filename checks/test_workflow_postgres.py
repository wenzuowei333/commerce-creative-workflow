import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import select as select_io
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, func, update

from app import models
from app.db import Base
from app.media import build_media_store
from app.providers import MockAIProvider
from app.services.generation_execution import process_item, reference_images
from app.services.generation_recovery import recover_stale_items
from app.services.generation_batches import refresh_batch_state
from conftest import ROOT, headers, prepare, start


def process(ctx, item_id, provider=None):
    with ctx.factory() as db:
        item=db.get(models.GenerationItem,item_id)
        owned=process_item(db,item=item,provider=provider or MockAIProvider(),media_store=build_media_store(ctx.settings),settings=ctx.settings,request_id=str(uuid4()))
        if owned: refresh_batch_state(db,db.get(models.GenerationBatch,item.batch_id))
        return owned


def payload(ctx,batch_id):
    r=ctx.client.get(f"/api/v1/generation-batches/{batch_id}");assert r.status_code==200,r.text
    return r.json()["data"]


def test_migration_matches_all_eighteen_models(ctx):
    with ctx.factory.kw["bind"].connect() as conn:
        assert not compare_metadata(MigrationContext.configure(conn,opts={"compare_type":True}),Base.metadata)
    assert len(Base.metadata.tables)==18


def test_risk_confirmation_cannot_be_omitted_or_downgraded(ctx):
    a=ctx.client.post(f"/api/v1/products/{ctx.product_id}/analysis",headers=headers(ctx)).json()["data"]
    for attrs in (a["result"]["attributes"],[],[{**x,"high_risk":False,"user_confirmed":True} for x in a["result"]["attributes"]]):
        r=ctx.client.post(f"/api/v1/analysis/{a['id']}/confirm",headers=headers(ctx),json={"profile":a["result"]["profile"],"attributes":attrs})
        assert r.status_code==409 and r.json()["error"]["code"]=="risk_confirmation_required"
    early=ctx.client.post("/api/v1/prompt-plans",headers=headers(ctx),json={"product_id":ctx.product_id,"generation_type":"main","image_count":5})
    assert early.status_code==409


def test_unconfirmed_plan_and_invalid_recipe_are_rejected(ctx):
    plan=prepare(ctx)
    with ctx.factory() as db:
        row=db.get(models.PromptPlan,plan["id"]);row.state="awaiting_prompt_confirmation";db.commit()
    r=ctx.client.post("/api/v1/generation-batches",headers=headers(ctx),json={"prompt_plan_id":plan["id"]})
    assert r.status_code==409
    invalid=copy.deepcopy(plan["plan"]);invalid["directions"][0]["variants"].pop()
    r=ctx.client.post(f"/api/v1/prompt-plans/{plan['id']}/confirm",headers=headers(ctx),json={"plan":invalid})
    assert r.status_code==422


@pytest.mark.parametrize("count,kind",[(5,"main"),(10,"main"),(15,"detail")])
def test_plan_count_order_and_reference_order(ctx,count,kind):
    plan=prepare(ctx,count,kind)
    assert len(plan["plan"]["directions"])==count//5
    with ctx.factory() as db:
        assets=db.scalars(select(models.ProductAsset).where(models.ProductAsset.product_id==ctx.product_id).order_by(models.ProductAsset.position)).all()
        for asset in assets: asset.is_primary=False
        assets[-1].is_primary=True;db.commit()
        refs=reference_images(db,ctx.product_id,build_media_store(ctx.settings))
        assert refs[0].name==assets[-1].original_name
        assert [x.name for x in refs[1:]]==[x.original_name for x in assets[:-1]]
    batch=start(ctx,plan)
    assert len(batch["items"])==count and [i["index"] for i in batch["items"]]==list(range(count))


def test_eight_concurrent_idempotent_requests_create_one_batch(ctx):
    plan=prepare(ctx)
    key=str(uuid4())
    def call(_):
        r=ctx.client.post("/api/v1/generation-batches",headers=headers(ctx,key),json={"prompt_plan_id":plan["id"],"demo_scenario":"success"})
        assert r.status_code==201,r.text
        return r.json()["data"]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(call,range(8)))
    assert len(set(ids))==1
    with ctx.factory() as db:
        assert db.scalar(select(func.count()).select_from(models.GenerationBatch))==1
        assert db.scalar(select(func.count()).select_from(models.GenerationItem))==5
    conflict=ctx.client.post("/api/v1/generation-batches",headers=headers(ctx,key),json={"prompt_plan_id":plan["id"],"demo_scenario":"partial_once"})
    assert conflict.status_code==409


def test_eight_concurrent_claims_invoke_provider_once(ctx):
    batch=start(ctx,prepare(ctx));item_id=batch["items"][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(lambda _:process(ctx,item_id),range(8)))
    assert sum(results)==1
    with ctx.factory() as db:
        assert db.get(models.GenerationItem,item_id).attempts==1
        assert db.scalar(select(func.count()).select_from(models.ImageAsset))==1
        assert db.scalar(select(func.sum(models.UsageLedger.units)))==1


def test_partial_failure_manual_retry_preserves_four_images_and_is_idempotent(ctx):
    batch=start(ctx,prepare(ctx),"partial_once")
    for i in batch["items"]: assert process(ctx,i["id"])
    first=payload(ctx,batch["id"])
    assert first["state"]=="partial" and first["progress"]==100
    assert [i["state"] for i in first["items"]]==["completed","completed","failed","completed","completed"]
    preserved={i["id"]:i["image"]["id"] for i in first["items"] if i["image"]}
    key=str(uuid4());route=f"/api/v1/generation-batches/{batch['id']}/retry-failed"
    r=ctx.client.post(route,headers=headers(ctx,key));assert r.status_code==200
    failed=first["items"][2]
    assert process(ctx,failed["id"])
    assert ctx.client.post(route,headers=headers(ctx,key)).status_code==200
    final=payload(ctx,batch["id"])
    assert final["state"]=="completed" and [i["attempts"] for i in final["items"]]==[1,1,2,1,1]
    assert all(i["image"]["id"]==preserved[i["id"]] for i in final["items"] if i["id"] in preserved)
    assert ctx.client.get("/api/v1/usage/daily").json()["data"]["image_attempts"]==6
    folder=ROOT/"runtime/test-evidence";folder.mkdir(parents=True,exist_ok=True)
    (folder/"partial-retry.json").write_text(json.dumps({"initial":first,"final":final,"preserved_image_ids":preserved},ensure_ascii=False,indent=2))


def test_cross_owner_cannot_read_reference_batch_events_or_results(ctx):
    batch=start(ctx,prepare(ctx));process(ctx,batch["items"][0]["id"])
    completed=payload(ctx,batch["id"])["items"][0]["image"]["id"]
    other=ctx.client.post("/api/v1/auth/login",json={"username":"demo_other","password":"LocalDemo-2026!"});assert other.status_code==200
    assert ctx.client.get("/api/v1/products").json()["data"]==[]
    assert ctx.client.get(f"/api/v1/products/{ctx.product_id}").status_code==404
    for suffix in ("", "/events"):
        assert ctx.client.get(f"/api/v1/generation-batches/{batch['id']}"+suffix).status_code==404
    assert ctx.client.get(f"/api/v1/images/{completed}/content").status_code==404
    assert ctx.client.get("/api/v1/history").json()["data"]["items"]==[]
    retry=ctx.client.post(f"/api/v1/generation-batches/{batch['id']}/retry-failed",headers={"Idempotency-Key":str(uuid4()),"X-CSRF-Token":other.json()["data"]["csrf_token"]})
    assert retry.status_code==404


def test_sse_last_event_id_resumes_persisted_terminal_events(ctx):
    batch=start(ctx,prepare(ctx))
    for i in batch["items"]:process(ctx,i["id"])
    route=f"/api/v1/generation-batches/{batch['id']}/events"
    full=ctx.client.get(route);assert full.status_code==200
    ids=[line[4:] for line in full.text.splitlines() if line.startswith("id: ")]
    assert len(ids)>5
    resumed=ctx.client.get(route,headers={"Last-Event-ID":ids[-3]})
    resumed_ids=[line[4:] for line in resumed.text.splitlines() if line.startswith("id: ")]
    assert resumed_ids==ids[-2:]
    assert ctx.client.get(route,headers={"Last-Event-ID":ids[-1]}).text==""


def test_batch_settings_snapshot_survives_later_plan_edits(ctx):
    plan=prepare(ctx);batch=start(ctx,plan)
    with ctx.factory() as db:
        row=db.get(models.PromptPlan,plan["id"]);edited=copy.deepcopy(row.plan_json);edited["size"]="1024x1536";row.plan_json=edited;row.active_version+=1;db.commit()
    process(ctx,batch["items"][0]["id"])
    final=payload(ctx,batch["id"])
    assert final["plan_version"]==1 and final["items"][0]["image"]["height"]==1024


def test_expired_lease_heartbeat_cannot_be_revived(ctx):
    batch=start(ctx,prepare(ctx));item_id=batch["items"][0]["id"]
    with ctx.factory() as db:
        item=db.get(models.GenerationItem,item_id);item.state="generating";item.lease_token="expired";item.lease_expires_at=datetime.now(UTC)-timedelta(seconds=1);db.commit()
        from app.services.generation_execution import LeaseHeartbeat
        heartbeat=LeaseHeartbeat(db,item_id=item_id,lease_token="expired",lease_seconds=10,heartbeat_seconds=0.02)
        heartbeat.start();time.sleep(0.08);heartbeat.stop()
        db.refresh(item);assert item.lease_expires_at<datetime.now(UTC)
        assert recover_stale_items(db)==[item_id]


def test_quota_is_atomic_across_two_claims(ctx):
    batch=start(ctx,prepare(ctx));limited=ctx.settings.model_copy(update={"image_daily_limit":1})
    def run(item_id):
        with ctx.factory() as db:
            return process_item(db,item=db.get(models.GenerationItem,item_id),provider=MockAIProvider(),media_store=build_media_store(limited),settings=limited,request_id=str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[i["id"] for i in batch["items"][:2]]))
    with ctx.factory() as db:
        assert db.scalar(select(func.sum(models.UsageLedger.units)))==1
        assert db.scalar(select(func.count()).select_from(models.ImageAsset))==1


def test_cancel_during_provider_rejects_result(ctx):
    batch=start(ctx,prepare(ctx));item_id=batch["items"][0]["id"]
    from threading import Event
    ready=Event();release=Event()
    class Waiting(MockAIProvider):
        def generate_image(self,**kwargs):
            content=super().generate_image(**kwargs);ready.set();assert release.wait(5);return content
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(process,ctx,item_id,Waiting());assert ready.wait(5)
        r=ctx.client.post(f"/api/v1/generation-batches/{batch['id']}/cancel",headers=headers(ctx));assert r.status_code==200
        release.set();assert future.result(timeout=5) is False
    with ctx.factory() as db:assert db.scalar(select(func.count()).select_from(models.ImageAsset))==0


def stop_process(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)


def child(ctx,item_id,wait=0,raise_after=False):
    command=[sys.executable,"-m","demo.fault_worker","--item",item_id,"--wait-after-provider",str(wait)]
    if raise_after:command.append("--raise-after")
    return subprocess.Popen(command,cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)


def ready(proc):
    readers,_,_=select_io.select([proc.stdout],[],[],10)
    assert readers,"Child provider did not become ready"
    line=proc.stdout.readline();assert 'provider_result_ready' in line,(line,proc.poll())
    return line.strip()


@pytest.mark.parametrize("fault",["kill","late_success","late_error"])
def test_real_process_recovery_and_late_result_fencing(ctx,fault):
    batch=start(ctx,prepare(ctx));item_id=batch["items"][0]["id"]
    old=child(ctx,item_id,30 if fault=="kill" else 2.5,raise_after=fault=="late_error")
    replacement=None
    try:
        first_log=ready(old)
        with ctx.factory() as db:
            item=db.get(models.GenerationItem,item_id);assert item.state=="generating" and item.attempts==1
            first={"attempt":item.attempts,"lease_token":item.lease_token,"state":item.state}
        if fault=="kill":os.killpg(old.pid,signal.SIGKILL);old.wait(timeout=5)
        else:os.killpg(old.pid,signal.SIGSTOP)
        deadline=time.monotonic()+5;recovered=[]
        while time.monotonic()<deadline:
            with ctx.factory() as db:recovered=recover_stale_items(db)
            if item_id in recovered:break
            time.sleep(0.05)
        assert item_id in recovered
        replacement=child(ctx,item_id);replacement_out,replacement_err=replacement.communicate(timeout=10)
        assert replacement.returncode==0,(replacement_out,replacement_err)
        with ctx.factory() as db:
            item=db.get(models.GenerationItem,item_id);saved=item.output_image_id
            assert item.state=="completed" and item.attempts==2 and saved
        old_out=""
        if fault!="kill":
            os.killpg(old.pid,signal.SIGCONT);old_out,old_err=old.communicate(timeout=10)
            assert old.returncode==0,(old_out,old_err)
            assert '"owned_write": false' in old_out
        with ctx.factory() as db:
            item=db.get(models.GenerationItem,item_id);assert item.output_image_id==saved and item.state=="completed"
            assert db.scalar(select(func.count()).select_from(models.ImageAsset))==1
            rejected=db.scalars(select(models.TaskEvent).where(models.TaskEvent.event_type=="stale_result_rejected")).all()
            if fault!="kill":assert len(rejected)==1
        folder=ROOT/"runtime/test-evidence";folder.mkdir(parents=True,exist_ok=True)
        (folder/f"process-{fault}.json").write_text(json.dumps({"fault":fault,"first":first,"first_log":first_log,"replacement":replacement_out.splitlines(),"resumed_old":old_out.splitlines(),"final_attempt":2,"saved_image_id_unchanged":saved,"image_rows":1},indent=2))
    finally:
        if old.poll() is None and fault!="kill":os.killpg(old.pid,signal.SIGCONT)
        stop_process(old)
        if replacement:stop_process(replacement)


def test_real_dramatiq_worker_completes_partial_and_manual_retry(ctx):
    log_path=ROOT/"runtime/dramatiq-test.log"
    with log_path.open("w") as log:
        worker=subprocess.Popen([sys.executable,"-m","dramatiq","app.workers.tasks","--processes","1","--threads","2"],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            batch=start(ctx,prepare(ctx),"partial_once")
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                first=payload(ctx,batch["id"])
                if first["state"]=="partial":break
                assert worker.poll() is None,log_path.read_text()
                time.sleep(0.05)
            assert first["state"]=="partial",log_path.read_text()
            assert len([i for i in first["items"] if i["state"]=="completed"])==4
            preserved={i["id"]:i["image"]["id"] for i in first["items"] if i["image"]}
            r=ctx.client.post(f"/api/v1/generation-batches/{batch['id']}/retry-failed",headers=headers(ctx));assert r.status_code==200
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                final=payload(ctx,batch["id"])
                if final["state"]=="completed":break
                time.sleep(0.05)
            assert final["state"]=="completed" and [i["attempts"] for i in final["items"]]==[1,1,2,1,1]
            assert all(i["image"]["id"]==preserved[i["id"]] for i in final["items"] if i["id"] in preserved)
            folder=ROOT/"runtime/test-evidence";folder.mkdir(parents=True,exist_ok=True)
            (folder/"dramatiq-partial-retry.json").write_text(json.dumps({"real_redis":True,"independent_dramatiq_process":True,"initial":first,"final":final,"four_original_image_ids_unchanged":True},ensure_ascii=False,indent=2))
        finally:stop_process(worker)


def test_reanalysis_invalidates_old_plan_in_api_and_workspace(ctx):
    plan=prepare(ctx)
    r=ctx.client.post(f"/api/v1/products/{ctx.product_id}/analysis",headers=headers(ctx));assert r.status_code==201
    a=r.json()["data"]
    for attr in a["result"]["attributes"]:attr["user_confirmed"]=True
    r=ctx.client.post(f"/api/v1/analysis/{a['id']}/confirm",headers=headers(ctx),json={"profile":a["result"]["profile"],"attributes":a["result"]["attributes"]});assert r.status_code==200
    assert ctx.client.get(f"/api/v1/products/{ctx.product_id}").json()["data"]["latest_prompt_plan"] is None
    r=ctx.client.post("/api/v1/generation-batches",headers=headers(ctx),json={"prompt_plan_id":plan["id"]})
    assert r.status_code==409 and r.json()["error"]["code"]=="prompt_plan_obsolete"


def test_live_heartbeat_prevents_takeover_beyond_initial_ttl(ctx):
    from threading import Event
    batch=start(ctx,prepare(ctx));item_id=batch["items"][0]["id"]
    ready_event=Event();release=Event()
    class LongProvider(MockAIProvider):
        def generate_image(self,**kwargs):
            content=super().generate_image(**kwargs);ready_event.set();assert release.wait(5);return content
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(process,ctx,item_id,LongProvider());assert ready_event.wait(5)
        time.sleep(ctx.settings.generation_lease_seconds+0.25)
        with ctx.factory() as db:
            assert recover_stale_items(db)==[]
            item=db.get(models.GenerationItem,item_id)
            assert item.state=="generating" and item.attempts==1
        release.set();assert future.result(timeout=5) is True
