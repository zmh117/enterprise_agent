import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@enterprise-agent/ui/components/button";

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { void error; void info; /* Never render raw details. */ }
  render() {
    if (this.state.failed) return <main className="app-loading"><div className="empty-panel"><strong>页面无法继续渲染</strong><p>敏感错误详情不会显示在浏览器中。请刷新页面；若问题持续，请提供请求 correlation id。</p><Button onClick={() => window.location.reload()}>刷新页面</Button></div></main>;
    return this.props.children;
  }
}
