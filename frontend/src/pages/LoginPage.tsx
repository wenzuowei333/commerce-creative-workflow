import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LockKeyhole, Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiRequest, setCsrfToken } from "../api/client";
import styles from "./LoginPage.module.css";

type Session = { user: { id: string; username: string }; csrf_token: string };

export function LoginPage() {
  const [username, setUsername] = useState("demo_admin");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () =>
      apiRequest<Session>("/auth/login", {
        method: "POST",
        body: { username, password },
      }),
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token);
      queryClient.setQueryData(["auth", "session"], session);
      navigate("/", { replace: true });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  return (
    <div className={styles.page}>
      <section className={styles.visual} aria-label="电商商品视觉工作室">
        <img src={`${import.meta.env.BASE_URL}demo-studio.svg`} alt="专业电商产品影棚陈列" />
        <div className={styles.visualCopy}>
          <span>AI 电商视觉</span>
          <h2>从商品素材到成套视觉，一处完成</h2>
          <p>识别商品、确认信息、策划提示词，再批量生成可持续迭代的图片版本。</p>
        </div>
      </section>
      <section className={styles.loginPane}>
        <div className={styles.formWrap}>
          <div className={styles.mark} aria-hidden="true">
            <Sparkles size={22} />
          </div>
          <h1>登录商品多模态创作工作台</h1>
          <p>使用 demo_admin 或 demo_other，密码 LocalDemo-2026!。</p>
          <form className={styles.form} onSubmit={submit}>
            <label className="field-label">
              账号
              <input
                className="field"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="field-label">
              密码
              <input
                className="field"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            {login.error && <p className={styles.error}>{login.error.message}</p>}
            <button className={`button ${styles.submit}`} type="submit" disabled={login.isPending}>
              {login.isPending ? "正在登录" : "登录工作台"}
            </button>
          </form>
          <div className={styles.security}>
            <LockKeyhole size={14} />
            合成数据与 Mock 输出，无需模型密钥
          </div>
        </div>
      </section>
    </div>
  );
}
