import { Link } from "wouter";
import { Card } from "../components/Card";

export function NotFoundPage() {
  return (
    <div className="page page--not-found">
      <div className="not-found">
        <Card accent padded>
          <p className="eyebrow">404</p>
          <h1>页面未找到</h1>
          <p>你访问的路径不存在。可能是旧链接被移除，或拼写有误。</p>
          <div>
            <Link href="/data" className="action action--primary">
              回到数据源
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
