import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/** Keeps a route-level failure from turning the entire console into a blank screen. */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="app-crash" role="alert">
          <div className="app-crash__card">
            <span className="app-crash__eyebrow">界面加载异常</span>
            <h1>这个页面暂时无法显示</h1>
            <p>已拦截前端错误，避免出现整页空白。刷新页面后可再次尝试。</p>
            <code>{this.state.error.message || "Unknown UI error"}</code>
            <button className="action action--primary" type="button" onClick={() => window.location.reload()}>
              刷新页面
            </button>
          </div>
        </main>
      );
    }

    return this.props.children;
  }
}
