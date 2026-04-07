function isMobileLayout() {
  // 動態檢測 .notes-grid 是否為單欄顯示
  // 透過檢查 Grid 的實際渲染結果，而非固定的 px 數字
  const notesGrid = document.querySelector('.notes-grid')
  
  if (!notesGrid) {
    // 如果找不到 Grid 元素，使用保守的寬度判斷
    return window.innerWidth <= 480
  }
  
  // 檢查 Grid 的 computed style
  const computedStyle = window.getComputedStyle(notesGrid)
  const gridTemplateColumns = computedStyle.gridTemplateColumns
  
  // 如果 grid-template-columns 只有一個值（單欄），返回 true
  // 例如: "1fr" 或 "500px" (單欄)
  // 多欄會是: "250px 250px" 或 "1fr 1fr" 等
  const columnCount = gridTemplateColumns.split(' ').filter(val => val && val !== 'none').length
  
  return columnCount <= 1
}

function needsWebGLControl() {
  return isMobileLayout()
}

class MapInstanceManager {
  constructor(maxInstances = 3) {
    this.maxInstances = maxInstances
    this.activeInstances = new Map()   // componentId -> { instanceId, priority }
    this.instanceCounter = 0
    this.needsControl = needsWebGLControl()
    this.desktopInteractiveMap = null
    this.desktopCallbacks = new Map()

    // 手機版：追蹤所有已註冊的 LocationMap 及其可見性狀態
    // componentId -> { visible: bool, onGrant: fn, onRevoke: fn }
    this._registered = new Map()
    this._scanScheduled = false
    this._scanDelay = 150  // debounce ms

    // 手機版：監聽 scroll 事件做 debounce rescan
    if (this.needsControl) {
      let scrollTimer = null
      window.addEventListener('scroll', () => {
        if (scrollTimer) clearTimeout(scrollTimer)
        scrollTimer = setTimeout(() => {
          this._scheduleScan()
        }, this._scanDelay)
      }, { passive: true })
    }
  }

  // === 手機版 LocationMap 註冊/取消 ===

  register(componentId, { onGrant, onRevoke }) {
    this._registered.set(componentId, {
      visible: false,
      onGrant,
      onRevoke
    })
  }

  unregister(componentId) {
    this._registered.delete(componentId)
    if (this.activeInstances.has(componentId)) {
      this.activeInstances.delete(componentId)
    }
    // 有空位了，重新掃描
    this._scheduleScan()
  }

  setVisible(componentId, visible) {
    const entry = this._registered.get(componentId)
    if (!entry) return
    if (entry.visible === visible) return
    entry.visible = visible
    this._scheduleScan()
  }

  // 外部觸發重新掃描（例如 view 切換後）
  triggerScan() {
    this._scheduleScan()
  }

  _scheduleScan() {
    if (this._scanScheduled) return
    this._scanScheduled = true
    // 使用 requestAnimationFrame + setTimeout 的組合確保 DOM 更新後再掃描
    requestAnimationFrame(() => {
      setTimeout(() => {
        this._scanScheduled = false
        this._doScan()
      }, 20)
    })
  }

  _doScan() {
    if (!this.needsControl) return

    // 1. 收集所有可見的 component（依優先級排序：visible > not visible）
    const visibleIds = []
    const invisibleActiveIds = []

    for (const [cid, entry] of this._registered.entries()) {
      if (entry.visible) {
        visibleIds.push(cid)
      } else if (this.activeInstances.has(cid)) {
        invisibleActiveIds.push(cid)
      }
    }

    // 2. 計算需要多少 slot 給可見的地圖
    const alreadyActiveVisible = visibleIds.filter(cid => this.activeInstances.has(cid))
    const needSlotVisible = visibleIds.filter(cid => !this.activeInstances.has(cid))

    let availableSlots = this.maxInstances - this.activeInstances.size

    // 3. 如果空位不夠，從不可見的 active instances 中回收
    if (needSlotVisible.length > availableSlots) {
      const toRevoke = invisibleActiveIds.slice(0, needSlotVisible.length - availableSlots)
      for (const cid of toRevoke) {
        this.activeInstances.delete(cid)
        const entry = this._registered.get(cid)
        if (entry && entry.onRevoke) {
          entry.onRevoke()
        }
        availableSlots++
      }
    }

    // 4. 授予可見地圖 slot
    for (const cid of needSlotVisible) {
      if (availableSlots <= 0) break
      const instanceId = ++this.instanceCounter
      this.activeInstances.set(cid, { instanceId, priority: 10 })
      const entry = this._registered.get(cid)
      if (entry && entry.onGrant) {
        entry.onGrant()
      }
      availableSlots--
    }
  }

  // === 相容舊 API（LocationPicker 等仍使用）===

  requestInstance(componentId, priority = 0) {
    return new Promise((resolve) => {
      if (!this.needsControl) {
        const instanceId = ++this.instanceCounter
        this.activeInstances.set(componentId, { instanceId, priority })
        resolve({ allowed: true, instanceId })
        return
      }

      if (this.activeInstances.size < this.maxInstances) {
        const instanceId = ++this.instanceCounter
        this.activeInstances.set(componentId, { instanceId, priority })
        resolve({ allowed: true, instanceId })
      } else {
        // 高優先級（如 LocationPicker priority=100）可搶佔低優先級的 slot
        const lowestActive = this._findLowestPriorityActive()
        if (lowestActive && lowestActive.priority < priority) {
          // 回收最低優先級的
          const entry = this._registered.get(lowestActive.componentId)
          this.activeInstances.delete(lowestActive.componentId)
          if (entry && entry.onRevoke) {
            entry.onRevoke()
          }
          const instanceId = ++this.instanceCounter
          this.activeInstances.set(componentId, { instanceId, priority })
          resolve({ allowed: true, instanceId })
        } else {
          resolve({ allowed: false, instanceId: null })
        }
      }
    })
  }

  releaseInstance(componentId) {
    if (this.activeInstances.has(componentId)) {
      this.activeInstances.delete(componentId)
      this._scheduleScan()
    }
  }

  updatePriority(componentId, newPriority) {
    if (this.activeInstances.has(componentId)) {
      const instance = this.activeInstances.get(componentId)
      instance.priority = newPriority
    }
  }

  _findLowestPriorityActive() {
    let lowest = null
    for (const [componentId, instance] of this.activeInstances.entries()) {
      if (!lowest || instance.priority < lowest.priority) {
        lowest = { componentId, ...instance }
      }
    }
    return lowest
  }

  getActiveCount() {
    return this.activeInstances.size
  }

  isActive(componentId) {
    return this.activeInstances.has(componentId)
  }

  requestDesktopInteractiveMap(componentId) {
    // 桌機版：一次只能有一個互動地圖
    if (isMobileLayout()) return

    // 如果已經有活動的互動地圖，先釋放它
    if (this.desktopInteractiveMap && this.desktopInteractiveMap !== componentId) {
      const callback = this.desktopCallbacks.get(this.desktopInteractiveMap)
      if (callback) {
        callback() // 通知舊地圖恢復成靜態圖
      }
      this.releaseInstance(this.desktopInteractiveMap)
    }

    // 設定新的互動地圖
    this.desktopInteractiveMap = componentId
    const instanceId = ++this.instanceCounter
    this.activeInstances.set(componentId, { instanceId, priority: 100 })
  }

  registerDesktopCallback(componentId, callback) {
    this.desktopCallbacks.set(componentId, callback)
  }

  unregisterDesktopCallback(componentId) {
    this.desktopCallbacks.delete(componentId)
    if (this.desktopInteractiveMap === componentId) {
      this.desktopInteractiveMap = null
    }
  }
}

const mapInstanceManager = new MapInstanceManager(3)

export { isMobileLayout, needsWebGLControl }
export default mapInstanceManager
