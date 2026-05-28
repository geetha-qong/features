export default function StudioFoot() {
  return (
    <footer className="studio-foot">
      <div className="keys">
        <kbd>K</kbd>
        <span>select</span>
        <kbd>E</kbd>
        <span>edit</span>
        <kbd>D</kbd>
        <span>flip direction</span>
        <kbd>L</kbd>
        <span>draw line</span>
        <kbd className="wide">space</kbd>
        <span>confirm</span>
      </div>
      <div style={{ flex: 1 }}></div>
      <div className="autosave">
        <span className="dot"></span>Auto-save 2s ago
      </div>
    </footer>
  );
}
