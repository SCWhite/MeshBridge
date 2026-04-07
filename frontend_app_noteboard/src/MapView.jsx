import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

const LOCATION_REGEX = /([\u4e00-\u9fa5a-zA-Z0-9_\-]+)?@\(([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\)/g

function parseLocationsFromText(text) {
  const locations = []
  let match
  const regex = new RegExp(LOCATION_REGEX.source, 'g')
  while ((match = regex.exec(text)) !== null) {
    locations.push({
      lat: parseFloat(match[2]),
      lng: parseFloat(match[3]),
      label: match[1] ? match[1].trim() : ''
    })
  }
  return locations.length > 0 ? locations : null
}

function stripLocationText(text) {
  return text.replace(LOCATION_REGEX, (match, label) => label || '').replace(/\s{2,}/g, ' ').trim()
}

// Strip all location patterns EXCEPT keep the label for the one at targetIndex
function stripOtherLocations(text, targetIndex) {
  let idx = 0
  return text.replace(LOCATION_REGEX, (match, label) => {
    const result = (idx === targetIndex) ? (label || '') : ''
    idx++
    return result
  }).replace(/\s{2,}/g, ' ').trim()
}

function MapView({ notes, boardId, isActive, onNavigateToNote, onCreateNoteFromMap }) {
  const mapContainer = useRef(null)
  const map = useRef(null)
  const markersRef = useRef([])
  const [mapEnabled, setMapEnabled] = useState(true)
  const [mapConfig, setMapConfig] = useState(null)
  const [zoomLimits, setZoomLimits] = useState({ minZoom: 0, maxZoom: 22 })
  const [isLoading, setIsLoading] = useState(true)
  const [mapReady, setMapReady] = useState(false)
  const expandedClustersRef = useRef(new Set())
  const zIndexCounter = useRef(100)
  const longPressTimerRef = useRef(null)
  const longPressPopupRef = useRef(null)
  const onCreateNoteFromMapRef = useRef(onCreateNoteFromMap)

  // Keep callback ref fresh
  useEffect(() => {
    onCreateNoteFromMapRef.current = onCreateNoteFromMap
  }, [onCreateNoteFromMap])

  // Filter notes: not archived + has coordinates
  const notesWithLocations = (notes || [])
    .filter(note => !note.archived && !note.deleted)
    .map(note => {
      const locations = parseLocationsFromText(note.text || '')
      if (!locations) return null
      return { ...note, locations }
    })
    .filter(Boolean)
    // Also include reply notes that have locations
    .reduce((acc, note) => {
      // Add parent note
      acc.push(note)
      // Check reply notes too
      if (note.replyNotes) {
        note.replyNotes.forEach(reply => {
          if (reply.archived || reply.deleted) return
          const locations = parseLocationsFromText(reply.text || '')
          if (locations) {
            acc.push({ ...reply, locations, isReply: true, parentBgColor: note.bgColor })
          }
        })
      }
      return acc
    }, [])

  // Fetch map config
  useEffect(() => {
    const fetchMapConfig = async () => {
      try {
        const response = await fetch('/api/available-tilesets')
        const data = await response.json()

        if (data.success && data.map_enabled) {
          setMapEnabled(true)
          setMapConfig(data)

          let styleUrl = '/tiles/style.json'
          if (data.layer_mode === 'single' && data.tilesets.length === 1) {
            styleUrl = `/tiles/${data.tilesets[0].name}/style.json`
          }

          const styleResponse = await fetch(styleUrl)
          const style = await styleResponse.json()

          const firstSource = Object.values(style.sources)[0]
          if (firstSource) {
            setZoomLimits({
              minZoom: firstSource.minzoom || 0,
              maxZoom: firstSource.maxzoom || 22
            })
          }
        } else {
          setMapEnabled(false)
        }
      } catch (error) {
        console.error('Failed to fetch map config:', error)
        setMapEnabled(false)
      } finally {
        setIsLoading(false)
      }
    }

    fetchMapConfig()
  }, [])

  // Initialize map
  useEffect(() => {
    if (!mapEnabled || !mapConfig || !mapContainer.current) return
    if (map.current) return

    let styleUrl = '/tiles/style.json'
    if (mapConfig.layer_mode === 'single' && mapConfig.tilesets.length === 1) {
      styleUrl = `/tiles/${mapConfig.tilesets[0].name}/style.json`
    }

    // Restore saved map state for this board, or use defaults
    let center = [121.5654, 25.0330]
    let initZoom = 13
    const storageKey = `mapview_state_${boardId || 'default'}`
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey))
      if (saved && saved.center && saved.zoom) {
        center = saved.center
        initZoom = saved.zoom
      } else if (notesWithLocations.length > 0) {
        const firstLoc = notesWithLocations[0].locations[0]
        center = [firstLoc.lng, firstLoc.lat]
      }
    } catch {
      if (notesWithLocations.length > 0) {
        const firstLoc = notesWithLocations[0].locations[0]
        center = [firstLoc.lng, firstLoc.lat]
      }
    }

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: styleUrl,
      center: center,
      zoom: initZoom,
      minZoom: zoomLimits.minZoom,
      maxZoom: Math.max(16, zoomLimits.maxZoom),
      dragRotate: false,
      touchPitch: false
    })

    map.current.touchZoomRotate.disableRotation()

    map.current.addControl(
      new maplibregl.NavigationControl({
        showCompass: false,
        showZoom: true,
        visualizePitch: false
      }),
      'top-right'
    )

    map.current.on('load', () => {
      // Only fit bounds if no saved state
      const hasSavedState = (() => {
        try {
          const s = JSON.parse(localStorage.getItem(storageKey))
          return s && s.center && s.zoom
        } catch { return false }
      })()

      if (!hasSavedState) {
        if (notesWithLocations.length > 1) {
          const bounds = new maplibregl.LngLatBounds()
          notesWithLocations.forEach(note => {
            note.locations.forEach(loc => {
              bounds.extend([loc.lng, loc.lat])
            })
          })
          map.current.fitBounds(bounds, { padding: 60, maxZoom: 15 })
        } else if (notesWithLocations.length === 1) {
          const loc = notesWithLocations[0].locations[0]
          map.current.setCenter([loc.lng, loc.lat])
          map.current.setZoom(14)
        }
      }
      console.log('[MapView] Map loaded and ready')
      setMapReady(true)
    })

    // Save map state on move/zoom
    const saveMapState = () => {
      if (!map.current) return
      const c = map.current.getCenter()
      const z = map.current.getZoom()
      try {
        localStorage.setItem(storageKey, JSON.stringify({
          center: [c.lng, c.lat],
          zoom: z
        }))
      } catch {}
    }
    map.current.on('moveend', saveMapState)

    return () => {
      clearMarkers()
      setMapReady(false)
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [mapEnabled, mapConfig, zoomLimits])

  // Create "open in sticky view" icon button for a note card
  const createGoToNoteBtn = (noteId) => {
    const btn = document.createElement('div')
    btn.className = 'mapview-goto-btn'
    btn.title = '在便利貼模式中檢視'
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      if (onNavigateToNote) onNavigateToNote(noteId)
    })
    return btn
  }

  const clearMarkers = useCallback(() => {
    markersRef.current.forEach(m => m.remove())
    markersRef.current = []
  }, [])

  // Build flat entries list from notes
  const buildEntries = useCallback(() => {
    const entries = []
    notesWithLocations.forEach(note => {
      note.locations.forEach((loc, locIdx) => {
        entries.push({ note, location: loc, locationIndex: locIdx })
      })
    })
    // Sort oldest first so newer get higher z-index
    entries.sort((a, b) => new Date(a.note.timestamp || 0) - new Date(b.note.timestamp || 0))
    return entries
  }, [notesWithLocations])

  // Pixel-based clustering with asymmetric thresholds (wider X for horizontal text boxes)
  const clusterEntries = useCallback((entries, thresholdX, thresholdY) => {
    if (!map.current) return []
    const clusters = []
    const assigned = new Set()

    // Project all entries to pixel coordinates
    const projected = entries.map(entry => {
      const pt = map.current.project([entry.location.lng, entry.location.lat])
      return { ...entry, px: pt.x, py: pt.y }
    })

    projected.forEach((entry, i) => {
      if (assigned.has(i)) return
      const cluster = [entry]
      assigned.add(i)
      for (let j = i + 1; j < projected.length; j++) {
        if (assigned.has(j)) continue
        const dx = Math.abs(entry.px - projected[j].px)
        const dy = Math.abs(entry.py - projected[j].py)
        if (dx < thresholdX && dy < thresholdY) {
          cluster.push(projected[j])
          assigned.add(j)
        }
      }
      clusters.push(cluster)
    })
    return clusters
  }, [])

  // Generate a stable cluster key from its member note IDs + locations
  const getClusterKey = (cluster) => {
    return cluster.map(e => `${e.note.noteId}@${e.location.lat},${e.location.lng}`).sort().join('|')
  }

  // Spiral layout: clockwise from 12 o'clock. 60° step for ≤6 notes, 30° for >6
  const calcSpiralOffsets = (count) => {
    if (count <= 1) return [[0, 0]]
    const ANGLE_STEP = count <= 6 ? (Math.PI / 3) : (Math.PI / 6)  // 60° or 30°
    const SLOTS_PER_RING = count <= 6 ? 6 : 12
    const BASE_RADIUS = 140
    const RING_GAP = 120
    const offsets = []
    for (let i = 0; i < count; i++) {
      const ring = Math.floor(i / SLOTS_PER_RING)
      const indexInRing = i % SLOTS_PER_RING
      const radius = BASE_RADIUS + ring * RING_GAP
      const angle = -Math.PI / 2 + ANGLE_STEP * indexInRing
      offsets.push([Math.cos(angle) * radius, Math.sin(angle) * radius])
    }
    return offsets
  }

  // Animate marker offsets from start to end over duration
  const animateMarkerOffsets = (markerOffsetPairs, duration, onFrame) => {
    const startTime = performance.now()
    const startOffsets = markerOffsetPairs.map(([m]) => {
      const o = m.getOffset()
      return [o.x || 0, o.y || 0]
    })
    const endOffsets = markerOffsetPairs.map(([, end]) => end)

    const step = (now) => {
      const t = Math.min((now - startTime) / duration, 1)
      const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t // easeInOutQuad
      markerOffsetPairs.forEach(([marker], i) => {
        const x = startOffsets[i][0] + (endOffsets[i][0] - startOffsets[i][0]) * ease
        const y = startOffsets[i][1] + (endOffsets[i][1] - startOffsets[i][1]) * ease
        marker.setOffset([x, y])
      })
      if (onFrame) onFrame(markerOffsetPairs, ease)
      if (t < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  // Render markers for given clusters
  const renderMarkers = useCallback((collapsingKey) => {
    if (!map.current) return
    clearMarkers()

    const entries = buildEntries()
    if (entries.length === 0) return

    // Build a global time-rank map: entries are already sorted oldest-first,
    // so index = rank. Newer notes get higher z-index.
    const timeRank = new Map()
    entries.forEach((entry, i) => {
      const key = entry.note.noteId + '@' + entry.location.lat + ',' + entry.location.lng
      timeRank.set(key, i + 1)
    })
    zIndexCounter.current = entries.length + 10

    // Asymmetric thresholds: wider horizontal (note cards are ~220px wide) vs vertical (~80px tall)
    const THRESHOLD_X = 160
    const THRESHOLD_Y = 100
    const clusters = clusterEntries(entries, THRESHOLD_X, THRESHOLD_Y)

    clusters.forEach((cluster) => {
      // Sort cluster: oldest first (bottom), newest last (top)
      cluster.sort((a, b) => new Date(a.note.timestamp || 0) - new Date(b.note.timestamp || 0))

      const clusterKey = getClusterKey(cluster)
      const isExpanded = expandedClustersRef.current.has(clusterKey)
      const isSingleNote = cluster.length === 1

      // Use first entry's location as cluster center
      const centerLoc = cluster[0].location
      const centerLngLat = [centerLoc.lng, centerLoc.lat]

      if (!isSingleNote && !isExpanded) {
        // === COLLAPSED: show only the newest note (top) with stack badge ===
        const topEntry = cluster[cluster.length - 1]
        const { note, location } = topEntry
        const displayText = stripOtherLocations(note.text || '', topEntry.locationIndex)
        const bgColor = note.bgColor || '#fffde7'
        const time = note.time || ''

        const el = document.createElement('div')
        el.className = 'mapview-marker-wrapper'
        const newestRank = timeRank.get(topEntry.note.noteId + '@' + topEntry.location.lat + ',' + topEntry.location.lng) || 1
        el.style.zIndex = newestRank

        // Shadow cards behind to indicate stack
        for (let s = Math.min(cluster.length - 1, 2); s > 0; s--) {
          const shadow = document.createElement('div')
          shadow.className = 'mapview-stack-shadow'
          shadow.style.backgroundColor = cluster[cluster.length - 1 - s].note.bgColor || '#fffde7'
          shadow.style.transform = `translate(${s * 3}px, ${-s * 3}px)`
          el.appendChild(shadow)
        }

        const card = document.createElement('div')
        card.className = 'mapview-note-card'
        card.style.backgroundColor = bgColor

        const contentDiv = document.createElement('div')
        contentDiv.className = 'mapview-note-text'
        contentDiv.textContent = displayText || '(無文字)'
        card.appendChild(contentDiv)

        const timeDiv = document.createElement('div')
        timeDiv.className = 'mapview-note-time'
        timeDiv.textContent = time
        card.appendChild(timeDiv)

        const badge = document.createElement('div')
        badge.className = 'mapview-stack-badge'
        badge.textContent = cluster.length
        card.appendChild(badge)

        if (note.noteId) card.appendChild(createGoToNoteBtn(note.noteId))

        const arrow = document.createElement('div')
        arrow.className = 'mapview-note-arrow'
        arrow.style.borderTopColor = bgColor

        el.appendChild(card)
        el.appendChild(arrow)

        // Click to expand with animation
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          expandedClustersRef.current.add(clusterKey)
          renderMarkers()
        })

        const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat([location.lng, location.lat])
          .addTo(map.current)
        markersRef.current.push(marker)

      } else if (!isSingleNote && isExpanded) {
        // === EXPANDED multi-note cluster ===
        const centerPx = map.current.project(centerLngLat)
        const svgNS = 'http://www.w3.org/2000/svg'
        const BASE_RADIUS = 140
        const RING_GAP = 120
        const MIN_GAP = Math.PI / 6  // 30° minimum between notes
        const SLOTS_PER_RING = Math.floor(2 * Math.PI / MIN_GAP)  // 12

        // Compute natural angle for each note relative to cluster center
        const notesWithAngles = cluster.map((entry) => {
          const noteLngLat = [entry.location.lng, entry.location.lat]
          const notePx = map.current.project(noteLngLat)
          const dx = notePx.x - centerPx.x
          const dy = notePx.y - centerPx.y
          const angle = (dx === 0 && dy === 0) ? -Math.PI / 2 : Math.atan2(dy, dx)
          return { entry, noteLngLat, dx, dy, angle }
        })

        // Sort by angle
        notesWithAngles.sort((a, b) => a.angle - b.angle)

        // Split into rings of max SLOTS_PER_RING (12) each
        const rings = []
        for (let start = 0; start < notesWithAngles.length; start += SLOTS_PER_RING) {
          rings.push(notesWithAngles.slice(start, start + SLOTS_PER_RING))
        }

        // For each ring, enforce MIN_GAP independently and compute offsets
        const noteData = []
        rings.forEach((ringNotes, ringIdx) => {
          const radius = BASE_RADIUS + ringIdx * RING_GAP
          const rn = ringNotes.length
          const angles = ringNotes.map(nd => nd.angle)

          // Forward pass: push notes apart if too close
          for (let i = 1; i < rn; i++) {
            if (angles[i] - angles[i - 1] < MIN_GAP) {
              angles[i] = angles[i - 1] + MIN_GAP
            }
          }

          // Check circular wrap
          if (rn > 1) {
            const circularGap = (angles[0] + 2 * Math.PI) - angles[rn - 1]
            if (circularGap < MIN_GAP) {
              const meanAngle = ringNotes.reduce((s, nd) => s + nd.angle, 0) / rn
              const totalSpan = (rn - 1) * MIN_GAP
              for (let i = 0; i < rn; i++) {
                angles[i] = meanAngle - totalSpan / 2 + i * MIN_GAP
              }
            }
          }

          ringNotes.forEach((nd, i) => {
            const ox = Math.cos(angles[i]) * radius
            const oy = Math.sin(angles[i]) * radius
            noteData.push({
              entry: nd.entry,
              noteLngLat: nd.noteLngLat,
              finalOffset: [ox - nd.dx, oy - nd.dy]
            })
          })
        })

        // 1. Per-note black dots at each note's original coordinate
        noteData.forEach(({ noteLngLat }) => {
          const dotEl = document.createElement('div')
          dotEl.className = 'mapview-center-dot'
          const dotMarker = new maplibregl.Marker({ element: dotEl, anchor: 'center' })
            .setLngLat(noteLngLat)
            .addTo(map.current)
          markersRef.current.push(dotMarker)
        })

        // 2. Per-note SVG connection lines (from dot to note card)
        const lineElements = []
        const lineWrappers = []
        noteData.forEach(({ entry, noteLngLat }) => {
          const svg = document.createElementNS(svgNS, 'svg')
          svg.setAttribute('width', '1')
          svg.setAttribute('height', '1')
          svg.style.overflow = 'visible'
          svg.style.pointerEvents = 'none'
          const line = document.createElementNS(svgNS, 'line')
          line.setAttribute('x1', 0)
          line.setAttribute('y1', 0)
          line.setAttribute('x2', 0)
          line.setAttribute('y2', 0)
          line.setAttribute('stroke', '#555')
          line.setAttribute('stroke-width', '1.5')
          line.setAttribute('stroke-dasharray', '4,3')
          line.setAttribute('opacity', '0.6')
          svg.appendChild(line)
          const wrapper = document.createElement('div')
          wrapper.style.pointerEvents = 'none'
          const lineRank = timeRank.get(entry.note.noteId + '@' + entry.location.lat + ',' + entry.location.lng) || 1
          wrapper.style.zIndex = lineRank - 1
          wrapper.appendChild(svg)
          const lineMarker = new maplibregl.Marker({ element: wrapper, anchor: 'center' })
            .setLngLat(noteLngLat)
            .addTo(map.current)
          markersRef.current.push(lineMarker)
          lineElements.push(line)
          lineWrappers.push(wrapper)
        })

        // 3. Collapse button at cluster center
        const hubEl = document.createElement('div')
        hubEl.className = 'mapview-hub'
        const btnEl = document.createElement('div')
        btnEl.className = 'mapview-collapse-btn'
        btnEl.textContent = '收合'
        btnEl.addEventListener('click', (e) => {
          e.stopPropagation()
          const pairs = noteMarkers.map((m, i) => [m, [0, 0]])
          animateMarkerOffsets(pairs, 180, (mp, ease) => {
            noteData.forEach(({ finalOffset }, i) => {
              lineElements[i].setAttribute('x2', finalOffset[0] * (1 - ease))
              lineElements[i].setAttribute('y2', finalOffset[1] * (1 - ease))
            })
            mp.forEach(([m]) => {
              m.getElement().style.opacity = 1 - ease * 0.5
            })
            if (ease >= 1) {
              expandedClustersRef.current.delete(clusterKey)
              renderMarkers()
            }
          })
        })
        hubEl.appendChild(btnEl)
        const hubMarker = new maplibregl.Marker({ element: hubEl, anchor: 'top', offset: [0, 10] })
          .setLngLat(centerLngLat)
          .addTo(map.current)
        markersRef.current.push(hubMarker)

        // 4. Note card markers at their original coordinates
        const noteMarkers = []
        noteData.forEach(({ entry, noteLngLat, finalOffset }, idx) => {
          const { note } = entry
          const displayText = stripOtherLocations(note.text || '', entry.locationIndex)
          const bgColor = note.bgColor || '#fffde7'
          const time = note.time || ''

          const el = document.createElement('div')
          el.className = 'mapview-marker-wrapper mapview-expanded-note'
          const rank = timeRank.get(entry.note.noteId + '@' + entry.location.lat + ',' + entry.location.lng) || 1
          el.style.zIndex = rank

          const card = document.createElement('div')
          card.className = 'mapview-note-card'
          card.style.backgroundColor = bgColor

          const contentDiv = document.createElement('div')
          contentDiv.className = 'mapview-note-text'
          contentDiv.textContent = displayText || '(無文字)'
          card.appendChild(contentDiv)

          const timeDiv = document.createElement('div')
          timeDiv.className = 'mapview-note-time'
          timeDiv.textContent = time
          card.appendChild(timeDiv)

          if (note.noteId) card.appendChild(createGoToNoteBtn(note.noteId))

          const isBelow = finalOffset[1] > 0
          const arrow = document.createElement('div')
          arrow.className = 'mapview-note-arrow' + (isBelow ? ' arrow-up' : '')
          if (isBelow) {
            arrow.style.borderBottomColor = bgColor
            el.appendChild(arrow)
            el.appendChild(card)
          } else {
            arrow.style.borderTopColor = bgColor
            el.appendChild(card)
            el.appendChild(arrow)
          }

          el.addEventListener('click', (e) => {
            e.stopPropagation()
            zIndexCounter.current += 2
            el.style.zIndex = zIndexCounter.current
            if (lineWrappers[idx]) lineWrappers[idx].style.zIndex = zIndexCounter.current - 1
          })

          // Place at note's original coordinate, animate offset outward
          const marker = new maplibregl.Marker({
            element: el,
            anchor: isBelow ? 'top' : 'bottom',
            offset: [0, 0]
          })
            .setLngLat(noteLngLat)
            .addTo(map.current)
          markersRef.current.push(marker)
          noteMarkers.push(marker)
        })

        // 5. Animate expand: notes fly out, lines grow
        const pairs = noteMarkers.map((m, i) => [m, noteData[i].finalOffset])
        animateMarkerOffsets(pairs, 200, (mp, ease) => {
          noteData.forEach(({ finalOffset }, i) => {
            lineElements[i].setAttribute('x2', finalOffset[0] * ease)
            lineElements[i].setAttribute('y2', finalOffset[1] * ease)
          })
        })

      } else {
        // === Single note: just show it ===
        const entry = cluster[0]
        const { note, location } = entry
        const displayText = stripOtherLocations(note.text || '', entry.locationIndex)
        const bgColor = note.bgColor || '#fffde7'
        const time = note.time || ''

        const el = document.createElement('div')
        el.className = 'mapview-marker-wrapper'
        const rank = timeRank.get(entry.note.noteId + '@' + entry.location.lat + ',' + entry.location.lng) || 1
        el.style.zIndex = rank

        const card = document.createElement('div')
        card.className = 'mapview-note-card'
        card.style.backgroundColor = bgColor

        const contentDiv = document.createElement('div')
        contentDiv.className = 'mapview-note-text'
        contentDiv.textContent = displayText || '(無文字)'
        card.appendChild(contentDiv)

        const timeDiv = document.createElement('div')
        timeDiv.className = 'mapview-note-time'
        timeDiv.textContent = time
        card.appendChild(timeDiv)

        if (note.noteId) card.appendChild(createGoToNoteBtn(note.noteId))

        const arrow = document.createElement('div')
        arrow.className = 'mapview-note-arrow'
        arrow.style.borderTopColor = bgColor

        el.appendChild(card)
        el.appendChild(arrow)

        el.addEventListener('click', (e) => {
          e.stopPropagation()
          zIndexCounter.current += 2
          el.style.zIndex = zIndexCounter.current
        })

        const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat([location.lng, location.lat])
          .addTo(map.current)
        markersRef.current.push(marker)

        // Black dot at the coordinate point
        const dotEl = document.createElement('div')
        dotEl.className = 'mapview-center-dot'
        const dotMarker = new maplibregl.Marker({ element: dotEl, anchor: 'center' })
          .setLngLat([location.lng, location.lat])
          .addTo(map.current)
        markersRef.current.push(dotMarker)
      }
    })
  }, [buildEntries, clusterEntries, clearMarkers])

  // Re-render markers when notes change or map becomes ready
  useEffect(() => {
    if (!mapReady) return
    renderMarkers()
  }, [mapReady, notes, renderMarkers])

  // Resize map when becoming active (after display:none the canvas size is stale)
  useEffect(() => {
    if (isActive && map.current) {
      map.current.resize()
    }
  }, [isActive])

  // Re-cluster on zoom change
  useEffect(() => {
    if (!map.current || !mapReady) return
    const onZoomEnd = () => {
      // Reset expanded state on zoom (clusters change)
      expandedClustersRef.current.clear()
      renderMarkers()
    }
    map.current.on('zoomend', onZoomEnd)
    return () => {
      if (map.current) map.current.off('zoomend', onZoomEnd)
    }
  }, [mapReady, renderMarkers])

  // Long-press to create note from map with visual progress ring
  useEffect(() => {
    if (!map.current || !mapReady) return

    const LONG_PRESS_DURATION = 1500
    const RING_DELAY = 500
    const MOVE_THRESHOLD = 10
    const RING_SIZE = 120
    let startPos = null
    let startScreenPoint = null
    let pressLngLat = null
    let progressRing = null
    let markerDot = null
    let ringDelayTimer = null
    let popupShown = false
    let pressing = false
    let closeClickHandler = null

    const clearLongPress = (reason) => {
      if (ringDelayTimer) {
        clearTimeout(ringDelayTimer)
        ringDelayTimer = null
      }
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current)
        longPressTimerRef.current = null
      }
      removeProgressRing()
      pressing = false
    }

    const removeProgressRing = () => {
      if (progressRing) {
        progressRing.remove()
        progressRing = null
      }
    }

    const removeMarkerDot = () => {
      if (markerDot) {
        markerDot.remove()
        markerDot = null
      }
    }

    const showMarkerDot = (lngLat) => {
      removeMarkerDot()
      if (!map.current) return

      const el = document.createElement('div')
      el.className = 'mapview-longpress-marker'

      const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat([lngLat.lng, lngLat.lat])
        .addTo(map.current)

      markerDot = marker
    }

    const removeLongPressPopup = () => {
      removeMarkerDot()
      removeCloseClickHandler()
      if (longPressPopupRef.current) {
        longPressPopupRef.current.remove()
        longPressPopupRef.current = null
      }
    }

    const removeCloseClickHandler = () => {
      if (closeClickHandler && map.current) {
        map.current.off('click', closeClickHandler)
        closeClickHandler = null
      }
    }

    const showProgressRing = (screenPoint) => {
      removeProgressRing()
      
      const container = mapContainer.current
      if (!container) return
      const ring = document.createElement('div')
      ring.className = 'mapview-progress-ring'
      ring.style.left = `${screenPoint.x - RING_SIZE / 2}px`
      ring.style.top = `${screenPoint.y - RING_SIZE / 2}px`
      ring.style.width = `${RING_SIZE}px`
      ring.style.height = `${RING_SIZE}px`
      ring.style.setProperty('--duration', `${LONG_PRESS_DURATION}ms`)

      ring.innerHTML = `
        <svg viewBox="0 0 100 100">
          <circle class="ring-bg" cx="50" cy="50" r="45" />
          <circle class="ring-progress" cx="50" cy="50" r="45" />
        </svg>
      `

      container.appendChild(ring)
      progressRing = ring

      // Double-rAF to ensure the initial state is painted before animation starts
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (progressRing === ring) {
            ring.classList.add('animating')
          }
        })
      })
    }

    const showLongPressPopup = (lngLat) => {
      if (!onCreateNoteFromMapRef.current || !map.current) return
      if (longPressPopupRef.current) {
        longPressPopupRef.current.remove()
        longPressPopupRef.current = null
      }

      showMarkerDot(lngLat)

      const container = document.createElement('div')
      container.className = 'mapview-longpress-popup'

      const title = document.createElement('div')
      title.className = 'mapview-longpress-title'
      title.textContent = '新增便利貼'
      container.appendChild(title)

      const coords = document.createElement('div')
      coords.className = 'mapview-longpress-coords'
      coords.textContent = `${lngLat.lat.toFixed(4)}, ${lngLat.lng.toFixed(4)}`
      container.appendChild(coords)

      const actions = document.createElement('div')
      actions.className = 'mapview-longpress-actions'

      const cancelBtn = document.createElement('button')
      cancelBtn.className = 'mapview-longpress-btn mapview-longpress-btn-cancel'
      cancelBtn.textContent = '取消'
      cancelBtn.addEventListener('click', (e) => {
        e.stopPropagation()
        removeLongPressPopup()
      })
      actions.appendChild(cancelBtn)

      const createBtn = document.createElement('button')
      createBtn.className = 'mapview-longpress-btn mapview-longpress-btn-create'
      createBtn.textContent = '建立'
      createBtn.addEventListener('click', (e) => {
        e.stopPropagation()
        removeLongPressPopup()
        if (onCreateNoteFromMapRef.current) {
          onCreateNoteFromMapRef.current(lngLat.lat, lngLat.lng)
        }
      })
      actions.appendChild(createBtn)

      container.appendChild(actions)

      const popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        anchor: 'bottom',
        offset: [0, -14]
      })
        .setLngLat([lngLat.lng, lngLat.lat])
        .setDOMContent(container)
        .addTo(map.current)

      // Clean up marker dot if popup is closed by any means
      popup.on('close', () => {
        removeMarkerDot()
        removeCloseClickHandler()
        longPressPopupRef.current = null
      })

      longPressPopupRef.current = popup

      // Suppress the immediate click event that fires after mouseup at the same position
      // Without this, the click event from the long-press release closes the popup
      const mapCanvas = map.current.getCanvasContainer()
      const suppressClick = (ev) => {
        ev.stopPropagation()
        ev.preventDefault()
      }
      mapCanvas.addEventListener('click', suppressClick, { once: true, capture: true })
      // Safety cleanup in case no click fires (e.g. user moved mouse)
      setTimeout(() => mapCanvas.removeEventListener('click', suppressClick, { capture: true }), 500)

      // After a delay, allow clicking the map to close the popup
      setTimeout(() => {
        if (!longPressPopupRef.current) return
        closeClickHandler = () => {
          removeLongPressPopup()
        }
        if (map.current) {
          map.current.on('click', closeClickHandler)
        }
      }, 600)
    }

    const handleStart = (e) => {
      const evtType = e.originalEvent.type
      // For touch: only single finger
      if (e.originalEvent.touches && e.originalEvent.touches.length > 1) return

      startPos = { x: e.point.x, y: e.point.y }
      startScreenPoint = { x: e.point.x, y: e.point.y }
      pressLngLat = { lat: e.lngLat.lat, lng: e.lngLat.lng }
      popupShown = false
      pressing = true

      // Clear any previous long press (but don't clear popupShown yet)
      if (ringDelayTimer) { clearTimeout(ringDelayTimer); ringDelayTimer = null }
      if (longPressTimerRef.current) { clearTimeout(longPressTimerRef.current); longPressTimerRef.current = null }
      removeProgressRing()

      ringDelayTimer = setTimeout(() => {
        showProgressRing(startScreenPoint)
        ringDelayTimer = null
      }, RING_DELAY)

      longPressTimerRef.current = setTimeout(() => {
        removeProgressRing()
        popupShown = true
        pressing = false
        showLongPressPopup(pressLngLat)
        longPressTimerRef.current = null
      }, RING_DELAY + LONG_PRESS_DURATION)
    }

    const handleMove = (e) => {
      if (!startPos || !pressing) return
      const dx = Math.abs(e.point.x - startPos.x)
      const dy = Math.abs(e.point.y - startPos.y)
      if (dx > MOVE_THRESHOLD || dy > MOVE_THRESHOLD) {
        clearLongPress('move threshold exceeded')
        startPos = null
      }
    }

    const handleEnd = (e) => {
      const evtType = e && e.originalEvent ? e.originalEvent.type : 'unknown'
      if (popupShown) {
        popupShown = false
        startPos = null
        return
      }
      clearLongPress('end: ' + evtType)
      startPos = null
    }

    const handleDragStart = () => {
      clearLongPress('dragstart')
      startPos = null
    }

    map.current.on('mousedown', handleStart)
    map.current.on('mousemove', handleMove)
    map.current.on('mouseup', handleEnd)
    map.current.on('touchstart', handleStart)
    map.current.on('touchmove', handleMove)
    map.current.on('touchend', handleEnd)
    map.current.on('touchcancel', handleEnd)
    map.current.on('dragstart', handleDragStart)

    return () => {
      clearLongPress('cleanup')
      removeLongPressPopup()
      removeMarkerDot()
      if (map.current) {
        map.current.off('mousedown', handleStart)
        map.current.off('mousemove', handleMove)
        map.current.off('mouseup', handleEnd)
        map.current.off('touchstart', handleStart)
        map.current.off('touchmove', handleMove)
        map.current.off('touchend', handleEnd)
        map.current.off('touchcancel', handleEnd)
        map.current.off('dragstart', handleDragStart)
      }
    }
  }, [mapReady])

  if (isLoading) {
    return (
      <div className="mapview-container">
        <div className="view-placeholder">
          <div className="view-placeholder-title">載入地圖中...</div>
        </div>
      </div>
    )
  }

  if (!mapEnabled) {
    return (
      <div className="mapview-container">
        <div className="view-placeholder">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#95a5a6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
            <circle cx="12" cy="9" r="2.5" />
          </svg>
          <div className="view-placeholder-title">地圖模式 Map View</div>
          <div className="view-placeholder-desc">地圖功能未啟用（請設定 mbtiles 檔案）</div>
        </div>
      </div>
    )
  }

  return (
    <div className="mapview-container">
      <div ref={mapContainer} className="mapview-map" />
      {notesWithLocations.length === 0 && (
        <div className="mapview-empty-hint">
          目前沒有包含座標的便利貼
        </div>
      )}
    </div>
  )
}

export default MapView
