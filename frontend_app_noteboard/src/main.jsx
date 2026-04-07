import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// Prevent pull-to-refresh in Android captive portal WebView (SwipeRefreshLayout)
// ONLY when MapView is active. In MapView all content is position:fixed so the
// body has no scrollable height — SwipeRefreshLayout sees scrollTop===0 and
// intercepts the pull-down gesture. We inject a spacer to keep the body scrollable
// and force scrollTop>=1 so canChildScrollUp() returns true.
;(function () {
  function isMapView() {
    return !!document.querySelector('.mapview-mode')
  }

  function ensureScrollOffset() {
    if (!isMapView()) return
    var el = document.scrollingElement || document.documentElement
    if (el.scrollTop <= 0) el.scrollTop = 1
  }

  // Inject an invisible spacer at the end of <body> so the page is always scrollable,
  // even when all visible content is position:fixed (e.g. MapView).
  function injectSpacer() {
    var spacer = document.createElement('div')
    spacer.style.cssText = 'height:3px;width:1px;pointer-events:none;visibility:hidden;position:relative;z-index:-1;'
    spacer.setAttribute('aria-hidden', 'true')
    document.body.appendChild(spacer)
  }

  if (document.body) {
    injectSpacer()
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      injectSpacer()
    })
  }

  window.addEventListener('scroll', function () {
    ensureScrollOffset()
  }, { passive: true })

  document.addEventListener('touchstart', function () {
    ensureScrollOffset()
  }, { passive: true })
})()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
