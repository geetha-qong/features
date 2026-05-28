import { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import qongMark from "../design/assets/qong-mark.png";
import { useAuth } from "../auth/AuthContext";

interface MarketingNavProps {
  /** active section key (for in-page scroll highlighting) */
  active?: string;
}

const NAV_LINKS: [string, string][] = [
  ["home",       "Home"],
  ["about",      "About"],
  ["product",    "Product"],
  ["technology", "Technology"],
  ["careers",    "Careers"],
  ["contact",    "Contact"],
];

export default function MarketingNav({ active = "home" }: MarketingNavProps) {
  const [current, setCurrent] = useState(active);
  const { user } = useAuth();

  const handleAnchorClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, key: string) => {
      e.preventDefault();
      setCurrent(key);
      const el = document.getElementById(key);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    []
  );

  return (
    <div className="mkt-nav-wrap">
      <nav className="mkt-nav">
        <Link
          to="/"
          className="brand"
          onClick={() => setCurrent("home")}
        >
          <img src={qongMark} alt="QONG" />
          <span className="text-gradient">QONG</span>
        </Link>

        <div className="spacer" />

        <div className="links">
          {NAV_LINKS.map(([key, label]) => (
            <a
              key={key}
              href={`#${key}`}
              className={current === key ? "active" : ""}
              onClick={(e) => handleAnchorClick(e, key)}
            >
              {label}
            </a>
          ))}
        </div>

        {user ? (
          <Link
            to="/dashboard"
            className="mkt-btn mkt-btn-primary mkt-btn-sm"
            style={{ marginLeft: 8 }}
          >
            Go to Dashboard
          </Link>
        ) : (
          <Link
            to="/signin"
            className="mkt-btn mkt-btn-primary mkt-btn-sm"
            style={{ marginLeft: 8 }}
          >
            Request Demo
          </Link>
        )}
      </nav>
    </div>
  );
}
