import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import mapInstanceManager from './MapInstanceManager'

let componentIdCounter = 0

function isAndroid() {
  const ua = navigator.userAgent.toLowerCase()
  return /android/.test(ua)
}

function isIOSSafari() {
  const ua = navigator.userAgent.toLowerCase()
  const isIOS = /iphone|ipad|ipod/.test(ua)
  const isSafari = /safari/.test(ua) && !/chrome|crios|fxios|edgios/.test(ua)
  return isIOS && isSafari
}

function needsWebGLControl() {
  return isAndroid() || isIOSSafari()
}

function LocationMap({ lat, lng, locations, zoom = 14 }) {
  const mapContainer = useRef(null)
  const map = useRef(null)
  const markers = useRef([])
  const [zoomLimits, setZoomLimits] = useState({ minZoom: 0, maxZoom: 22 })
  const [mapEnabled, setMapEnabled] = useState(true)
  const [mapConfig, setMapConfig] = useState(null)
  const [isVisible, setIsVisible] = useState(!needsWebGLControl())
  const [canRenderMap, setCanRenderMap] = useState(!needsWebGLControl())
  const componentId = useRef(`location-map-${++componentIdCounter}`)
  const observerRef = useRef(null)
  const needsControl = useRef(needsWebGLControl())

  useEffect(() => {
    // 不需要 WebGL 控制的設備：跳過 Intersection Observer
    if (!needsControl.current) return
    if (!mapContainer.current) return

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const visible = entry.isIntersecting
          setIsVisible(visible)
          
          if (visible) {
            mapInstanceManager.updatePriority(componentId.current, 10)
          } else {
            mapInstanceManager.updatePriority(componentId.current, 1)
          }
        })
      },
      {
        root: null,
        rootMargin: '50px',
        threshold: 0.1
      }
    )

    observer.observe(mapContainer.current)
    observerRef.current = observer

    return () => {
      if (observerRef.current && mapContainer.current) {
        observerRef.current.unobserve(mapContainer.current)
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
    const requestMapInstance = async () => {
      // 不需要 WebGL 控制的設備：直接允許渲染
      if (!needsControl.current) {
        setCanRenderMap(true)
        return
      }

      // 需要 WebGL 控制的設備（Android Chrome / iOS Safari）：檢查可見性並請求實例
      if (!isVisible) {
        setCanRenderMap(false)
        return
      }

      const result = await mapInstanceManager.requestInstance(componentId.current, 10)
      setCanRenderMap(result.allowed)
    }

    requestMapInstance()
  }, [isVisible])

  useEffect(() => {
    if (map.current) return
    if (!mapEnabled || !mapConfig) return
    if (!canRenderMap) return

    const locationsList = locations || (lat !== undefined && lng !== undefined ? [{ lat, lng }] : [])
    
    if (locationsList.length === 0) return

    const firstLocation = locationsList[0]
    
    // 根據 layer_mode 決定使用哪個 style.json
    let styleUrl = '/tiles/style.json'
    if (mapConfig.layer_mode === 'single' && mapConfig.tilesets.length === 1) {
      styleUrl = `/tiles/${mapConfig.tilesets[0].name}/style.json`
    }
    
    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: styleUrl,
      center: [firstLocation.lng, firstLocation.lat],
      zoom: zoom,
      minZoom: zoomLimits.minZoom,
      maxZoom: zoomLimits.maxZoom - 0.05,
      dragRotate: false,
      touchPitch: false,
      cooperativeGestures: true
    })

    map.current.touchZoomRotate.disableRotation()

    const markerColors = ['#FF5252', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0', '#FF9800', '#00BCD4', '#E91E63']
    
    locationsList.forEach((location, index) => {
      const color = markerColors[index % markerColors.length]
      
      const markerElement = document.createElement('div')
      markerElement.style.width = '30px'
      markerElement.style.height = '40px'
      markerElement.innerHTML = `
        <svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg" style="display: block; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
          <path d="M15 0C8.373 0 3 5.373 3 12c0 9 12 28 12 28s12-19 12-28c0-6.627-5.373-12-12-12z" 
                fill="${color}" 
                stroke="white" 
                stroke-width="2"/>
          <circle cx="15" cy="12" r="4" fill="white"/>
        </svg>
      `
      
      if (location.label) {
        const labelDiv = document.createElement('div')
        labelDiv.textContent = location.label
        labelDiv.style.position = 'absolute'
        labelDiv.style.bottom = '44px'
        labelDiv.style.left = '50%'
        labelDiv.style.transform = 'translateX(-50%)'
        labelDiv.style.backgroundColor = 'white'
        labelDiv.style.color = '#333'
        labelDiv.style.padding = '2px 6px'
        labelDiv.style.borderRadius = '3px'
        labelDiv.style.fontSize = '12px'
        labelDiv.style.fontWeight = 'bold'
        labelDiv.style.whiteSpace = 'nowrap'
        labelDiv.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)'
        labelDiv.style.pointerEvents = 'none'
        markerElement.appendChild(labelDiv)
      }
      
      const marker = new maplibregl.Marker({ 
        element: markerElement,
        anchor: 'bottom'
      })
        .setLngLat([location.lng, location.lat])
        .addTo(map.current)
      
      markers.current.push(marker)
    })

    if (locationsList.length > 1) {
      const bounds = new maplibregl.LngLatBounds()
      locationsList.forEach(location => {
        bounds.extend([location.lng, location.lat])
      })
      map.current.fitBounds(bounds, { padding: 50, maxZoom: 15 })
    }

    map.current.addControl(
      new maplibregl.NavigationControl({
        showCompass: false,
        showZoom: true,
        visualizePitch: false
      }),
      'top-right'
    )

    return () => {
      markers.current.forEach(marker => marker.remove())
      markers.current = []
      if (map.current) {
        map.current.remove()
        map.current = null
      }
      // 只在需要 WebGL 控制的設備上釋放實例
      if (needsControl.current) {
        mapInstanceManager.releaseInstance(componentId.current)
        setCanRenderMap(false)
      }
    }
  }, [zoomLimits, canRenderMap])

  useEffect(() => {
    if (!map.current) return

    const locationsList = locations || (lat !== undefined && lng !== undefined ? [{ lat, lng }] : [])
    
    if (locationsList.length === 0) return

    markers.current.forEach(marker => marker.remove())
    markers.current = []

    const markerColors = ['#FF5252', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0', '#FF9800', '#00BCD4', '#E91E63']
    
    locationsList.forEach((location, index) => {
      const color = markerColors[index % markerColors.length]
      
      const markerElement = document.createElement('div')
      markerElement.style.width = '30px'
      markerElement.style.height = '40px'
      markerElement.innerHTML = `
        <svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg" style="display: block; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
          <path d="M15 0C8.373 0 3 5.373 3 12c0 9 12 28 12 28s12-19 12-28c0-6.627-5.373-12-12-12z" 
                fill="${color}" 
                stroke="white" 
                stroke-width="2"/>
          <circle cx="15" cy="12" r="4" fill="white"/>
        </svg>
      `
      
      if (location.label) {
        const labelDiv = document.createElement('div')
        labelDiv.textContent = location.label
        labelDiv.style.position = 'absolute'
        labelDiv.style.bottom = '44px'
        labelDiv.style.left = '50%'
        labelDiv.style.transform = 'translateX(-50%)'
        labelDiv.style.backgroundColor = 'white'
        labelDiv.style.color = '#333'
        labelDiv.style.padding = '2px 6px'
        labelDiv.style.borderRadius = '3px'
        labelDiv.style.fontSize = '12px'
        labelDiv.style.fontWeight = 'bold'
        labelDiv.style.whiteSpace = 'nowrap'
        labelDiv.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)'
        labelDiv.style.pointerEvents = 'none'
        markerElement.appendChild(labelDiv)
      }
      
      const marker = new maplibregl.Marker({ 
        element: markerElement,
        anchor: 'bottom'
      })
        .setLngLat([location.lng, location.lat])
        .addTo(map.current)
      
      markers.current.push(marker)
    })

    if (locationsList.length === 1) {
      map.current.setCenter([locationsList[0].lng, locationsList[0].lat])
    } else if (locationsList.length > 1) {
      const bounds = new maplibregl.LngLatBounds()
      locationsList.forEach(location => {
        bounds.extend([location.lng, location.lat])
      })
      map.current.fitBounds(bounds, { padding: 50, maxZoom: 15 })
    }
  }, [lat, lng, locations])

  if (!mapEnabled) {
    return (
      <div style={{
        width: '98%',
        margin: '0 auto',
        height: '240px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#f5f5f5',
        borderRadius: '8px',
        color: '#666',
        fontSize: '14px'
      }}>
        地圖功能未啟用（請設定 mbtiles 檔案）
      </div>
    )
  }

  if (!canRenderMap) {
    const locationsList = locations || (lat !== undefined && lng !== undefined ? [{ lat, lng }] : [])
    const firstLocation = locationsList[0] || { lat: 0, lng: 0 }
    
    return (
      <div 
        ref={mapContainer}
        style={{ 
          width: '98%', 
          margin: '0 auto',
          boxShadow: '0 4px 8px rgba(0,0,0,0.2)',
          height: '240px',
          borderRadius: '8px',
          overflow: 'hidden',
          backgroundColor: '#e8e8e8',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          color: '#666',
          fontSize: '14px',
          position: 'relative'
        }}
      >
        <div style={{ marginBottom: '8px' }}>📍</div>
        <div style={{ fontSize: '12px', opacity: 0.7 }}>
          {firstLocation.lat.toFixed(4)}, {firstLocation.lng.toFixed(4)}
        </div>
        {!isVisible && (
          <div style={{ fontSize: '11px', marginTop: '4px', opacity: 0.5 }}>
            捲動至此處載入地圖
          </div>
        )}
      </div>
    )
  }

  return (
    <div 
      ref={mapContainer} 
      style={{ 
        width: '98%', 
        margin: '0 auto',
        boxShadow: '0 4px 8px rgba(0,0,0,0.2)',
        height: '240px',
        borderRadius: '8px',
        overflow: 'hidden'
      }} 
    />
  )
}

export default LocationMap
