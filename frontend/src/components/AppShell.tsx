import { useQuery } from "@tanstack/react-query";
import {
  Clock3,
  Images,
  ImagePlus,
  LayoutTemplate,
  LogOut,
  Sparkles,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { apiRequest } from "../api/client";
import { useSystemInfo } from "../features/system/api";
import styles from "./AppShell.module.css";

type Props = {
  username: string;
  onLogout: () => void;
};

const navItems = [
  { to: "/", label: "创作工作台", icon: ImagePlus, end: true },
  { to: "/assets", label: "素材库", icon: Images },
  { to: "/templates", label: "模板库", icon: LayoutTemplate },
  { to: "/history", label: "生成历史", icon: Clock3 },
];

export function AppShell({ username, onLogout }: Props) {
  const system = useSystemInfo();
  const usage = useQuery({
    queryKey: ["usage", "daily"],
    queryFn: () =>
      apiRequest<{ image_attempts: number; limit: number; remaining: number }>("/usage/daily"),
    refetchInterval: 60_000,
  });
  const visibleNavItems = navItems.filter(
    (item) => item.to !== "/templates" || system.features.templates,
  );

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true">
            <Sparkles size={20} />
          </div>
          <div>
            <strong>商品视觉工作流演示</strong>
            <span>合成商品 · Mock 工作流</span>
          </div>
        </div>
        <nav className={styles.nav} aria-label="主导航">
          {visibleNavItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.active : ""}`
              }
            >
              <item.icon size={19} aria-hidden="true" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.account}>
          <div className={styles.avatar}>{username.slice(0, 1).toUpperCase()}</div>
          <div className={styles.accountText}>
            <strong>{username}</strong>
            <span>本地演示账号</span>
          </div>
          <button className={`icon-button ${styles.logout}`} onClick={onLogout} title="退出登录">
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <main className={styles.main}>
        <header className={styles.topbar}>
          {system.data?.mode === "demo" && (
            <span className={styles.demoBadge}>Mock 演示模式</span>
          )}
          <div className={styles.usage}>
            今日生成
            <strong>{usage.data?.image_attempts ?? 0}</strong>
            <span>/ {usage.data?.limit ?? 200} 张</span>
          </div>
        </header>
        <div className={styles.content}>
          <Outlet />
        </div>
      </main>
      <nav className={styles.mobileNav} aria-label="移动端导航">
        {visibleNavItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `${styles.mobileLink} ${isActive ? styles.mobileLinkActive : ""}`
            }
          >
            <item.icon size={20} aria-hidden="true" />
            {item.label.replace("生成", "")}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
