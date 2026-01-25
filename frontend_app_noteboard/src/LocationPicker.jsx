import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import mapInstanceManager from './MapInstanceManager'

let pickerIdCounter = 0

function isAndroid() {
  const ua = navigator.userAgent.toLowerCase()
  return /android/.test(ua)
}

function LocationPicker({ onConfirm, onCancel, initialLat = 25.0330, initialLng = 121.5654, initialText = '', lastLocation = null }) {
  const mapContainer = useRef(null)
  const map = useRef(null)
  const markers = useRef([])
  const selectedIndexRef = useRef(0)
  const MAX_LOCATIONS = 5
  const componentId = useRef(`location-picker-${++pickerIdCounter}`)
  const isAndroidDevice = useRef(isAndroid())
  const [canRenderMap, setCanRenderMap] = useState(!isAndroid())

  const parseLocationsFromText = (text) => {
    const locationRegex = /([\u4e00-\u9fa5a-zA-Z0-9_\-]+)?@\(([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\)/g
    const locations = []
    let match
    
    while ((match = locationRegex.exec(text)) !== null) {
      const location = {
        lat: parseFloat(match[2]),
        lng: parseFloat(match[3]),
        label: match[1] ? match[1].trim() : ''
      }
      locations.push(location)
      
      if (locations.length >= MAX_LOCATIONS) break
    }
    
    return locations
  }

  const getInitialLocations = () => {
    if (initialText) {
      const parsedLocations = parseLocationsFromText(initialText)
      if (parsedLocations.length > 0) {
        return parsedLocations
      }
    }
    if (lastLocation) {
      return [{ lat: lastLocation.lat, lng: lastLocation.lng, label: '' }]
    }
    return [{ lat: initialLat, lng: initialLng, label: '' }]
  }

  const getInitialZoom = () => {
    if (initialText) {
      const parsedLocations = parseLocationsFromText(initialText)
      if (parsedLocations.length > 0) {
        return parsedLocations.length === 1 ? 13 : 12
      }
    }
    if (lastLocation && lastLocation.zoom) {
      return lastLocation.zoom
    }
    return 13
  }

  const [locations, setLocations] = useState(getInitialLocations())
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [zoomLimits, setZoomLimits] = useState({ minZoom: 0, maxZoom: 22 })
  const [mapEnabled, setMapEnabled] = useState(true)
  const [mapConfig, setMapConfig] = useState(null)

  useEffect(() => {
    selectedIndexRef.current = selectedIndex
  }, [selectedIndex])

  useEffect(() => {
    const requestMapInstance = async () => {
      // 非 Android 設備：直接允許渲染
      if (!isAndroidDevice.current) {
        setCanRenderMap(true)
        return
      }

      // Android 設備：請求實例（最高優先級）
      const result = await mapInstanceManager.requestInstance(componentId.current, 100)
      setCanRenderMap(result.allowed)
    }

    requestMapInstance()

    return () => {
      // 只在 Android 設備上釋放實例
      if (isAndroidDevice.current) {
        mapInstanceManager.releaseInstance(componentId.current)
      }
    }
  }, [])

  useEffect(() => {
    const fetchMapConfig = async () => {
      try {
        const response = await fetch('/api/available-tilesets')
        const data = await response.json()
        
        if (data.success && data.map_enabled) {
          setMapEnabled(true)
          setMapConfig(data)
          
          // 根據 layer_mode 決定使用哪個 style.json
          let styleUrl = '/tiles/style.json'
          if (data.layer_mode === 'single' && data.tilesets.length === 1) {
            // 單一 tileset，使用專屬的 style.json（支援 vector tiles）
            styleUrl = `/tiles/${data.tilesets[0].name}/style.json`
          }
          
          const styleResponse = await fetch(styleUrl)
          const style = await styleResponse.json()
          
          const firstSource = Object.values(style.sources)[0]
          if (firstSource) {
            const minZoom = firstSource.minzoom || 0
            const maxZoom = firstSource.maxzoom || 22
            setZoomLimits({ minZoom, maxZoom })
          }
        } else {
          setMapEnabled(false)
          console.log('Map disabled:', data.message)
        }
      } catch (error) {
        console.error('Failed to fetch map config:', error)
        setMapEnabled(false)
      }
    }
    
    fetchMapConfig()
  }, [])

  useEffect(() => {
    if (map.current) return
    if (!mapEnabled || !mapConfig) return
    if (!canRenderMap) return

    const initialZoom = getInitialZoom()

    // 根據 layer_mode 決定使用哪個 style.json
    let styleUrl = '/tiles/style.json'
    if (mapConfig.layer_mode === 'single' && mapConfig.tilesets.length === 1) {
      styleUrl = `/tiles/${mapConfig.tilesets[0].name}/style.json`
    }

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: styleUrl,
      center: [locations[0].lng, locations[0].lat],
      zoom: initialZoom,
      minZoom: zoomLimits.minZoom,
      maxZoom: zoomLimits.maxZoom - 0.05,
      dragRotate: false,
      touchPitch: false
    })

    map.current.touchZoomRotate.disableRotation()

    map.current.on('click', (e) => {
      const { lng, lat } = e.lngLat
      updateLocation(selectedIndexRef.current, { lat, lng })
    })

    map.current.addControl(
      new maplibregl.NavigationControl({
        showCompass: false,
        showZoom: true,
        visualizePitch: false
      }),
      'top-right'
    )
    
    map.current.on('load', () => {
      setLocations([...locations])
    })

    return () => {
      markers.current.forEach(marker => marker.remove())
      markers.current = []
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [zoomLimits, canRenderMap])

  useEffect(() => {
    if (!map.current) return

    markers.current.forEach(marker => marker.remove())
    markers.current = []

    const markerColors = ['#FF5252', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0']

    locations.forEach((location, index) => {
      const color = markerColors[index % markerColors.length]
      
      const markerElement = document.createElement('div')
      markerElement.style.width = '30px'
      markerElement.style.height = '40px'
      markerElement.style.cursor = 'pointer'
      markerElement.innerHTML = `
        <svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg" style="display: block; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
          <path d="M15 0C8.373 0 3 5.373 3 12c0 9 12 28 12 28s12-19 12-28c0-6.627-5.373-12-12-12z" 
                fill="${color}" 
                stroke="${selectedIndex === index ? '#FFD700' : 'white'}" 
                stroke-width="${selectedIndex === index ? '3' : '2'}"/>
          <circle cx="15" cy="12" r="4" fill="white"/>
        </svg>
      `
      
      const marker = new maplibregl.Marker({ 
        element: markerElement,
        anchor: 'bottom',
        draggable: true
      })
        .setLngLat([location.lng, location.lat])
        .addTo(map.current)
      
      marker.on('dragend', () => {
        const lngLat = marker.getLngLat()
        updateLocation(index, { lat: lngLat.lat, lng: lngLat.lng })
      })

      markerElement.addEventListener('click', (e) => {
        e.stopPropagation()
        setSelectedIndex(index)
      })
      
      markers.current.push(marker)
    })
  }, [locations, selectedIndex])

  const updateLocation = (index, newCoords) => {
    setLocations(prev => {
      const updated = [...prev]
      updated[index] = { ...updated[index], ...newCoords }
      return updated
    })
  }

  const updateLabel = (index, label) => {
    setLocations(prev => {
      const updated = [...prev]
      updated[index] = { ...updated[index], label }
      return updated
    })
  }

  const addLocation = () => {
    if (locations.length < MAX_LOCATIONS) {
      const center = map.current.getCenter()
      setLocations(prev => [...prev, { lat: center.lat, lng: center.lng, label: '' }])
      setSelectedIndex(locations.length)
    }
  }

  const removeLocation = (index) => {
    if (locations.length > 1) {
      setLocations(prev => prev.filter((_, i) => i !== index))
      setSelectedIndex(Math.max(0, Math.min(selectedIndex, locations.length - 2)))
    }
  }

  const handleConfirm = () => {
    const coordinateStrings = locations.map(loc => {
      const lat = loc.lat.toFixed(6)
      const lng = loc.lng.toFixed(6)
      const label = loc.label.trim()
      return label ? `${label}@(${lat},${lng})` : `@(${lat},${lng})`
    })
    
    const coordinateString = coordinateStrings.join(' ')
    
    const mapState = map.current ? {
      center: map.current.getCenter(),
      zoom: map.current.getZoom()
    } : null
    
    onConfirm(coordinateString, mapState)
  }

  if (!mapEnabled) {
    return (
      <div className="modal-overlay" onClick={onCancel}>
        <div className="modal-content location-picker-modal" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">選擇地圖座標</div>
          <div className="modal-body">
            <div style={{
              width: '100%',
              height: '400px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: '#f5f5f5',
              borderRadius: '8px',
              color: '#666',
              fontSize: '14px',
              marginBottom: '12px'
            }}>
              地圖功能未啟用（請設定 mbtiles 檔案）
            </div>
          </div>
          <div className="modal-actions">
            <button className="modal-btn modal-btn-cancel" onClick={onCancel}>
              關閉
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content location-picker-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">選擇地圖座標</div>
        <div className="modal-body">
          <div className="location-picker-instructions">
            點擊地圖或拖曳標記來選擇位置 ({locations.length}/{MAX_LOCATIONS})
          </div>
          {!canRenderMap ? (
            <div
              style={{
                width: '100%',
                height: '400px',
                borderRadius: '8px',
                overflow: 'hidden',
                marginBottom: '12px',
                backgroundColor: '#f0f0f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#666',
                fontSize: '14px'
              }}
            >
              正在載入地圖...
            </div>
          ) : (
            <div 
              ref={mapContainer}
              className="location-picker-map"
              style={{ 
                width: '100%', 
                height: '400px',
                borderRadius: '8px',
                overflow: 'hidden',
                marginBottom: '12px'
              }} 
            />
          )}
          <div className="location-list">
            {locations.map((location, index) => (
              <div 
                key={index} 
                className={`location-item ${selectedIndex === index ? 'selected' : ''}`}
                onClick={() => setSelectedIndex(index)}
              >
                <div className="location-item-header">
                  <span className="location-number" style={{ 
                    backgroundColor: ['#FF5252', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0'][index % 5]
                  }}>
                    {index + 1}
                  </span>
                  <div className="location-coords-small">
                    <span>{location.lat.toFixed(6)},</span>
                    <span>{location.lng.toFixed(6)}</span>
                  </div>
                  <input
                    type="text"
                    className="location-label-input-small"
                    placeholder="位置標籤 (選填)"
                    value={location.label}
                    onChange={(e) => updateLabel(index, e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    maxLength={20}
                  />
                  {locations.length > 1 && (
                    <button 
                      className="btn-remove-location"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeLocation(index)
                      }}
                      title="移除此點"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {locations.length < MAX_LOCATIONS && (
            <button className="btn-add-location" onClick={addLocation}>
              + 再增加一組座標點
            </button>
          )}
        </div>
        <div className="modal-actions">
          <button className="modal-btn modal-btn-cancel" onClick={onCancel}>
            取消
          </button>
          <button className="modal-btn modal-btn-confirm" onClick={handleConfirm}>
            確定
          </button>
        </div>
      </div>
    </div>
  )
}

export default LocationPicker
