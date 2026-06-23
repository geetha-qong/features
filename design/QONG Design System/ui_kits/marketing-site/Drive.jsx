/* global React */
const { useState, useEffect } = React;

function QongDrive() {
  const [progress, setProgress] = useState({ ins: 0, val: 0, pip: 0 });
  useEffect(() => {
    const id = setInterval(() => {
      setProgress((p) => ({
        ins: Math.min(p.ins + 3, 80),
        val: Math.min(p.val + 2, 60),
        pip: Math.min(p.pip + 3, 90),
      }));
    }, 90);
    return () => clearInterval(id);
  }, []);

  const wrap = {
    background: 'linear-gradient(180deg, #161931 0%, #0e1024 100%)',
    border: '1px solid #2a2e4a',
    borderRadius: 16,
    padding: 18,
    boxShadow: '0 0 0 1px rgba(139,63,206,0.18), 0 30px 80px rgba(0,0,0,0.5)',
    fontFamily: 'var(--font-sans)',
    color: '#E6E8F3',
  };
  const cap = { fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.15em', textTransform: 'uppercase', color: '#9498AE' };
  const tagPill = (color) => ({
    fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
    padding: '3px 7px', borderRadius: 4, background: `${color}22`, color, border: `1px solid ${color}55`,
  });

  return (
    <div style={wrap}>
      {/* header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: 12, borderBottom: '1px dashed #2a2e4a' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: '#fff' }} className="text-gradient"><span className="qong-mark">QONG</span> Drive</div>
          <div style={cap}>P&amp;ID Intelligence v1.0</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={tagPill('#22D3EE')}>SCANNING</span>
          <span style={tagPill('#8B3FCE')}><span className="qong-mark">QONG</span>-PID-001 · R3</span>
        </div>
      </div>

      {/* extracted instruments */}
      <div style={{ marginTop: 14 }}>
        <div style={{ ...cap, marginBottom: 8 }}>Extracted Data · 12 instruments found</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {[
            ['LT-301', 'Level Xmtr', '#8B3FCE'],
            ['PT-101', 'Press Xmtr', '#5347CC'],
            ['FT-201', 'Flow Xmtr', '#2E3FBE'],
            ['TT-401', 'Temp Xmtr', '#C73FBE'],
          ].map(([tag, name, c]) => (
            <div key={tag} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 10px', background: '#1a1d35', borderRadius: 6, border: '1px solid #2a2e4a',
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 12, color: c }}>{tag}</span>
              <span style={{ fontSize: 11, color: '#9498AE' }}>{name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* valves */}
      <div style={{ marginTop: 14 }}>
        <div style={{ ...cap, marginBottom: 8 }}>Valves</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <div style={{ padding: '8px 10px', background: '#1a1d35', borderRadius: 6, border: '1px solid #2a2e4a', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            <span style={{ color: '#22D3EE', fontWeight: 700 }}>V-102</span> <span style={{ color: '#9498AE' }}>Gate · 4&quot; · CS</span>
          </div>
          <div style={{ padding: '8px 10px', background: '#1a1d35', borderRadius: 6, border: '1px solid #2a2e4a', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            <span style={{ color: '#22D3EE', fontWeight: 700 }}>V-101</span> <span style={{ color: '#9498AE' }}>Ball · 2&quot; · SS</span>
          </div>
        </div>
      </div>

      {/* progress */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px dashed #2a2e4a' }}>
        <div style={{ ...cap, marginBottom: 8 }}>Progress</div>
        {[['Instruments', progress.ins], ['Valves', progress.val], ['Pipelines', progress.pip]].map(([l, v]) => (
          <div key={l} style={{ marginBottom: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3, color: '#BFC2D2' }}>
              <span>{l}</span><span style={{ fontFamily: 'var(--font-mono)', color: '#22D3EE' }}>{v}%</span>
            </div>
            <div style={{ height: 4, background: '#1a1d35', borderRadius: 999, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${v}%`, background: 'var(--qong-gradient)', transition: 'width 200ms' }} />
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#10B981' }}>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: '#10B981', boxShadow: '0 0 8px #10B981' }} />
        Processing Active
      </div>
    </div>
  );
}

window.QongDrive = QongDrive;
