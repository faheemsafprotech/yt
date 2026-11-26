const { useState, useEffect, useRef } = React;

function App() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [videoInfo, setVideoInfo] = useState(null);
  
  // Format selection
  const [activeTab, setActiveTab] = useState('video'); // 'video' | 'audio'
  const [selectedFormat, setSelectedFormat] = useState(null);

  // Background Download Progress State
  const [downloadTask, setDownloadTask] = useState(null);
  const pollIntervalRef = useRef(null);

  // Bot Bypass State
  const [showBypass, setShowBypass] = useState(false);
  const [bypassVerifying, setBypassVerifying] = useState(false);
  const [isBypassed, setIsBypassed] = useState(false);

  // Download History in LocalStorage
  const [history, setHistory] = useState(() => {
    try {
      const saved = localStorage.getItem('yt_download_history');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const saveToHistory = (item) => {
    try {
      const updated = [item, ...history.filter(h => h.id !== item.id)].slice(0, 10);
      setHistory(updated);
      localStorage.setItem('yt_download_history', JSON.stringify(updated));
    } catch (e) {
      console.warn('Could not save history to localStorage:', e);
    }
  };

  const clearHistory = () => {
    setHistory([]);
    localStorage.removeItem('yt_download_history');
  };

  // Duration formatting (HH:MM:SS or MM:SS)
  const formatDuration = (sec) => {
    if (!sec) return '';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return [
      h > 0 ? h : null,
      h > 0 ? String(m).padStart(2, '0') : m,
      String(s).padStart(2, '0')
    ].filter(x => x !== null).join(':');
  };

  const formatViews = (views) => {
    if (!views) return '';
    if (views >= 1000000000) return `${(views / 1000000000).toFixed(1)}B views`;
    if (views >= 1000000) return `${(views / 1000000).toFixed(1)}M views`;
    if (views >= 1000) return `${(views / 1000).toFixed(1)}K views`;
    return `${views} views`;
  };

  // Clipboard Paste Helper
  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        setUrl(text.trim());
      }
    } catch (err) {
      console.log('Clipboard access denied, focusing input.');
    }
  };

  // Analyze URL
  const handleAnalyze = async (e, useBypass = false) => {
    if (e) e.preventDefault();
    if (!url.trim()) return;

    setLoading(true);
    setLoadingMsg(useBypass ? 'Connecting with alternative security protocol...' : 'Analyzing video stream details...');
    setError('');
    setSuccess('');
    setDownloadTask(null);

    if (!useBypass) {
      setVideoInfo(null);
      setShowBypass(false);
      setIsBypassed(false);
    }

    try {
      const res = await fetch('/api/info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim(), bypass: useBypass })
      });

      const data = await res.json();
      if (!res.ok) {
        if (res.status === 403 && data.error === 'bot_challenge') {
          setShowBypass(true);
          throw new Error('Platform bot check triggered. Please complete the quick verification below.');
        }
        throw new Error(data.error || 'Failed to retrieve video information.');
      }

      setVideoInfo(data);
      setIsBypassed(useBypass);

      // Default format selection
      if (data.video_formats && data.video_formats.length > 0) {
        setSelectedFormat(data.video_formats[0]);
        setActiveTab('video');
      } else if (data.audio_formats && data.audio_formats.length > 0) {
        setSelectedFormat(data.audio_formats[0]);
        setActiveTab('audio');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setLoadingMsg('');
    }
  };

  // Handle Tab Change
  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab === 'video' && videoInfo && videoInfo.video_formats && videoInfo.video_formats.length > 0) {
      setSelectedFormat(videoInfo.video_formats[0]);
    } else if (tab === 'audio' && videoInfo && videoInfo.audio_formats && videoInfo.audio_formats.length > 0) {
      setSelectedFormat(videoInfo.audio_formats[0]);
    }
  };

  // Start Real-time Background Download
  const handleStartDownload = async () => {
    if (!videoInfo || !selectedFormat) return;

    setError('');
    setSuccess('');

    const isAudio = !selectedFormat.is_video;
    const payload = {
      url: url.trim(),
      mode: isAudio ? 'audio' : 'video',
      format_id: selectedFormat.format_id,
      audio_codec: selectedFormat.audio_codec || 'mp3',
      audio_quality: selectedFormat.audio_quality || '320',
      title: videoInfo.title,
      bypass: isBypassed
    };

    setDownloadTask({
      status: 'starting',
      stage: 'Initializing download worker...',
      percent: 0,
      speed: '0 KB/s',
      eta: '--',
      filename: null,
      filesize_str: ''
    });

    try {
      const res = await fetch('/api/download/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start download task.');

      pollProgress(data.task_id);
    } catch (err) {
      setError(err.message);
      setDownloadTask(null);
    }
  };

  // Poll Download Task Progress
  const pollProgress = (taskId) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/download/progress/${taskId}`);
        if (!res.ok) {
          clearInterval(pollIntervalRef.current);
          throw new Error('Download task not found or timed out.');
        }

        const task = await res.json();
        setDownloadTask(task);

        if (task.status === 'completed') {
          clearInterval(pollIntervalRef.current);
          setSuccess('Your file has been generated and is ready to save!');

          // Save to history
          saveToHistory({
            id: taskId,
            title: videoInfo.title,
            format: selectedFormat.label,
            size: task.filesize_str,
            download_url: task.download_url,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          });

          // Automatically trigger file download
          if (task.download_url) {
            const tempLink = document.createElement('a');
            tempLink.href = task.download_url;
            tempLink.setAttribute('download', task.filename || 'video.mp4');
            document.body.appendChild(tempLink);
            tempLink.click();
            document.body.removeChild(tempLink);
          }
        } else if (task.status === 'error') {
          clearInterval(pollIntervalRef.current);
          setError(task.error || 'Download failed during processing.');
        }
      } catch (err) {
        clearInterval(pollIntervalRef.current);
        setError(err.message);
      }
    }, 850);
  };

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const handleBypassClick = () => {
    if (bypassVerifying || isBypassed) return;
    setBypassVerifying(true);
    setTimeout(() => {
      setBypassVerifying(false);
      setIsBypassed(true);
      handleAnalyze(null, true);
    }, 1200);
  };

  const handleReset = () => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setUrl('');
    setVideoInfo(null);
    setSelectedFormat(null);
    setDownloadTask(null);
    setError('');
    setSuccess('');
    setShowBypass(false);
    setIsBypassed(false);
  };

  return (
    <div className="main-card">
      {/* Header */}
      <div className="app-header">
        <div className="app-badge-row">
          <div className="engine-pill">
            <span className="dot"></span>
            Universal Video & Audio Engine
          </div>
        </div>
        <h1>Video Downloader</h1>
        <p>Save high-definition 4K, 1080p videos & MP3 audio with crystal-clear sound from your favorite platforms.</p>
        
        <div className="platform-badges">
          <span className="platform-chip">YouTube</span>
          <span className="platform-chip">TikTok</span>
          <span className="platform-chip">Instagram</span>
          <span className="platform-chip">X (Twitter)</span>
          <span className="platform-chip">Facebook</span>
          <span className="platform-chip">Reddit</span>
          <span className="platform-chip">Vimeo</span>
          <span className="platform-chip">Pinterest</span>
          <span className="platform-chip">1000+ Sites</span>
        </div>
      </div>

      {/* Main Input Form */}
      {!videoInfo ? (
        <div>
          <form onSubmit={(e) => handleAnalyze(e, false)}>
            <div className="input-group">
              <div className="input-container">
                <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                </svg>
                <input
                  type="text"
                  className="url-input"
                  placeholder="Paste video link here (YouTube, TikTok, Instagram, X...)"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  disabled={loading}
                  required
                />
                <div className="input-actions">
                  {url ? (
                    <button type="button" className="icon-clear-btn" onClick={() => setUrl('')} title="Clear">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                      </svg>
                    </button>
                  ) : (
                    <button type="button" className="action-btn-sm" onClick={handlePaste} title="Paste from clipboard">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path>
                        <rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect>
                      </svg>
                      Paste
                    </button>
                  )}
                </div>
              </div>
            </div>

            {!showBypass && (
              <button type="submit" className="btn-primary" disabled={loading || !url.trim()}>
                {loading ? (
                  <>
                    <div className="spinner"></div>
                    <span>{loadingMsg}</span>
                  </>
                ) : (
                  <>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8"></circle>
                      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <span>Analyze Video</span>
                  </>
                )}
              </button>
            )}
          </form>

          {/* Bot Challenge Box */}
          {showBypass && (
            <div className="bypass-card" onClick={handleBypassClick}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                <div className={`bypass-checkbox ${isBypassed ? 'verified' : ''}`}>
                  {bypassVerifying ? (
                    <div className="spinner" style={{ width: '14px', height: '14px', borderLeftColor: '#6366f1' }}></div>
                  ) : isBypassed ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                  ) : null}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem', color: '#fff' }}>I am human (Verify with Bypass Engine)</div>
                  <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>Bypasses cloud restrictions and loads streams safely.</div>
                </div>
              </div>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
            </div>
          )}
        </div>
      ) : (
        /* Video Details & Format Selection Screen */
        <div>
          {/* Metadata Preview */}
          <div className="video-card">
            <div className="video-thumb-container">
              <img src={videoInfo.thumbnail} alt={videoInfo.title} className="video-thumb" />
              {videoInfo.duration > 0 && (
                <div className="badge-duration">{formatDuration(videoInfo.duration)}</div>
              )}
              {videoInfo.platform && (
                <div className="badge-platform" style={{ color: videoInfo.platform.color || '#fff' }}>
                  {videoInfo.platform.name}
                </div>
              )}
            </div>

            <div className="video-meta">
              <h3 className="video-title" title={videoInfo.title}>{videoInfo.title}</h3>
              <div className="video-creator">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                  <circle cx="12" cy="7" r="4"></circle>
                </svg>
                <span>{videoInfo.uploader}</span>
              </div>
              <div className="video-stats">
                {videoInfo.view_count && <span>{formatViews(videoInfo.view_count)}</span>}
                {videoInfo.duration > 0 && <span>• {formatDuration(videoInfo.duration)}</span>}
              </div>
            </div>
          </div>

          {/* Active Download Progress Widget */}
          {downloadTask && downloadTask.status !== 'completed' && (
            <div className="progress-card">
              <div className="progress-header">
                <div className="progress-stage">
                  <div className="spinner" style={{ width: '16px', height: '16px' }}></div>
                  <span>{downloadTask.stage}</span>
                </div>
                <div className="progress-percent">{downloadTask.percent}%</div>
              </div>

              <div className="progress-bar-bg">
                <div className="progress-bar-fill" style={{ width: `${downloadTask.percent}%` }}></div>
              </div>

              <div className="progress-stats-row">
                <span>Speed: {downloadTask.speed || '--'}</span>
                <span>ETA: {downloadTask.eta || '--'}</span>
                <span>Processed: {downloadTask.percent}%</span>
              </div>
            </div>
          )}

          {/* Download Complete Card */}
          {downloadTask && downloadTask.status === 'completed' && (
            <div className="success-card">
              <div className="success-icon-wrap">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                  <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
              </div>
              <h3>Download Ready!</h3>
              <p>Your video has been processed and saved successfully.</p>
              
              <div className="file-info-pill">
                <span>{downloadTask.filename}</span>
                {downloadTask.filesize_str && <span>({downloadTask.filesize_str})</span>}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <a 
                  href={downloadTask.download_url} 
                  download={downloadTask.filename} 
                  className="btn-primary" 
                  style={{ textDecoration: 'none' }}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                  </svg>
                  <span>Save to Disk</span>
                </a>
                
                <button onClick={handleReset} className="btn-secondary">
                  Download Another Video
                </button>
              </div>
            </div>
          )}

          {/* Format Selection (Visible when not actively downloading) */}
          {(!downloadTask || downloadTask.status === 'error') && (
            <div>
              {/* Format Tabs Switch */}
              <div className="format-tabs">
                <button
                  type="button"
                  className={`tab-btn ${activeTab === 'video' ? 'active' : ''}`}
                  onClick={() => handleTabChange('video')}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect>
                    <line x1="7" y1="2" x2="7" y2="22"></line>
                    <line x1="17" y1="2" x2="17" y2="22"></line>
                    <line x1="2" y1="12" x2="22" y2="12"></line>
                    <line x1="2" y1="7" x2="7" y2="7"></line>
                    <line x1="2" y1="17" x2="7" y2="17"></line>
                    <line x1="17" y1="17" x2="22" y2="17"></line>
                    <line x1="17" y1="7" x2="22" y2="7"></line>
                  </svg>
                  Video (MP4)
                </button>
                <button
                  type="button"
                  className={`tab-btn ${activeTab === 'audio' ? 'active' : ''}`}
                  onClick={() => handleTabChange('audio')}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 18V5l12-2v13"></path>
                    <circle cx="6" cy="18" r="3"></circle>
                    <circle cx="18" cy="16" r="3"></circle>
                  </svg>
                  Audio (MP3 / M4A)
                </button>
              </div>

              {/* Quality Options Grid */}
              <div className="format-grid">
                {(activeTab === 'video' ? (videoInfo.video_formats || []) : (videoInfo.audio_formats || [])).map((fmt) => {
                  const isSelected = selectedFormat && selectedFormat.format_id === fmt.format_id;
                  const is4k = fmt.height >= 2160;
                  const isFhd = fmt.height >= 1080 && !is4k;

                  return (
                    <div
                      key={fmt.format_id}
                      className={`format-item ${isSelected ? 'selected' : ''}`}
                      onClick={() => setSelectedFormat(fmt)}
                    >
                      <div className="format-left">
                        <div className="format-radio">
                          {isSelected && <div className="format-radio-dot"></div>}
                        </div>
                        <div className="format-details">
                          <h4>{fmt.label}</h4>
                          <p>{fmt.sub_label}</p>
                        </div>
                      </div>

                      <div className="format-right">
                        <span className={`badge-quality ${is4k ? 'badge-4k' : (isFhd ? 'badge-fhd' : '')}`}>
                          {fmt.quality_badge}
                        </span>
                        <span className="badge-ext">.{fmt.ext}</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <button onClick={handleStartDownload} className="btn-primary" disabled={!selectedFormat}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                  </svg>
                  <span>Download {selectedFormat ? selectedFormat.label : 'Selection'}</span>
                </button>

                <button onClick={handleReset} className="btn-secondary">
                  Choose another video link
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="alert alert-error">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <div>{error}</div>
        </div>
      )}

      {/* Success Message */}
      {success && !downloadTask && (
        <div className="alert alert-success">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          <div>{success}</div>
        </div>
      )}

      {/* Recent Downloads Tray */}
      {history.length > 0 && (
        <div className="history-section">
          <div className="history-header">
            <span className="history-title">Recent Downloads ({history.length})</span>
            <button className="history-clear-btn" onClick={clearHistory}>Clear</button>
          </div>
          <div className="history-list">
            {history.map((item) => (
              <div key={item.id} className="history-item">
                <span className="history-item-title" title={item.title}>
                  {item.title} ({item.format})
                </span>
                <span className="history-item-time">{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
