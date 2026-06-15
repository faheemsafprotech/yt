const { useState } = React;

function App() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [videoInfo, setVideoInfo] = useState(null);
  const [selectedFormatId, setSelectedFormatId] = useState('best');

  const formatDuration = (seconds) => {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return [
      h > 0 ? h : null,
      h > 0 ? String(m).padStart(2, '0') : m,
      String(s).padStart(2, '0')
    ].filter(x => x !== null).join(':');
  };

  const handleFetchInfo = async (e) => {
    e.preventDefault();
    if (!url) return;

    setLoading(true);
    setLoadingMessage('Fetching video details...');
    setError('');
    setSuccess('');
    setVideoInfo(null);

    try {
      const response = await fetch('/api/info', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to fetch video details.');
      }

      setVideoInfo(data);
      if (data.formats && data.formats.length > 0) {
        setSelectedFormatId(data.formats[0].format_id);
      } else {
        setSelectedFormatId('best');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleDownload = () => {
    if (!url) return;

    setSuccess("Download initiated! Please check your browser's download manager/drawer.");
    setError('');

    // Trigger download directly in the browser using the direct streaming download link
    const downloadUrl = `/api/download/direct?url=${encodeURIComponent(url)}&format_id=${encodeURIComponent(selectedFormatId)}&title=${encodeURIComponent(videoInfo.title)}`;
    window.location.href = downloadUrl;
  };

  const handleReset = () => {
    setUrl('');
    setVideoInfo(null);
    setSelectedFormatId('best');
    setError('');
    setSuccess('');
  };

  return (
    <div className="card">
      <div className="header">
        <h1>YouTube Downloader</h1>
        <p>Convert and download YouTube videos in high quality</p>
      </div>

      {!videoInfo ? (
        <form onSubmit={handleFetchInfo}>
          <div className="form-group">
            <div className="input-wrapper">
              <svg className="input-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
              </svg>
              <input
                type="url"
                className="url-input"
                placeholder="Paste YouTube video link here..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
                disabled={loading}
              />
            </div>
          </div>

          <button type="submit" className="btn" disabled={loading || !url}>
            {loading ? (
              <>
                <div className="spinner"></div>
                <span>{loadingMessage}</span>
              </>
            ) : (
              <span>Analyze URL</span>
            )}
          </button>
        </form>
      ) : (
        <div>
          <div className="preview-card">
            <div className="thumbnail-wrapper">
              <img src={videoInfo.thumbnail} alt={videoInfo.title} className="thumbnail" />
              {videoInfo.duration && (
                <div className="duration-tag">{formatDuration(videoInfo.duration)}</div>
              )}
            </div>
            <div className="video-info">
              <h3 className="video-title">{videoInfo.title}</h3>
              <p className="video-channel">By {videoInfo.uploader || 'Unknown Creator'}</p>
            </div>
          </div>

          {videoInfo.formats && videoInfo.formats.length > 0 && (
            <div className="form-group" style={{ marginTop: '20px' }}>
              <label className="select-label" htmlFor="quality-select">Select Quality / Format</label>
              <div className="select-wrapper">
                <select
                  id="quality-select"
                  className="quality-select"
                  value={selectedFormatId}
                  onChange={(e) => setSelectedFormatId(e.target.value)}
                  disabled={loading}
                >
                  {videoInfo.formats.map((f) => (
                    <option key={f.format_id} value={f.format_id}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <button 
              onClick={handleDownload} 
              className="btn" 
              disabled={loading}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>Download Selection</span>
            </button>

            <button 
              onClick={handleReset} 
              className="btn" 
              style={{ 
                background: 'rgba(255,255,255,0.05)', 
                border: '1px solid var(--card-border)',
                color: 'var(--text-primary)',
                boxShadow: 'none'
              }}
              disabled={loading}
            >
              <span>Download another video</span>
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <div>{error}</div>
        </div>
      )}

      {success && (
        <div className="alert alert-success">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          <div>{success}</div>
        </div>
      )}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
