import qongMark from "../design/assets/qong-mark.png";

export default function BrandRow({ size = 28 }: { size?: number }) {
  return (
    <div className="brand-row">
      <img src={qongMark} alt="QONG" style={{ width: size, height: size }} />
      <span className="brand-name">
        <span className="qm">QONG</span>&nbsp;Studio
      </span>
    </div>
  );
}
