function isAndroid() {
  const ua = navigator.userAgent.toLowerCase()
  return /android/.test(ua)
}

class MapInstanceManager {
  constructor(maxInstances = 3) {
    this.maxInstances = maxInstances
    this.activeInstances = new Map()
    this.pendingQueue = []
    this.instanceCounter = 0
    this.isAndroidDevice = isAndroid()
  }

  requestInstance(componentId, priority = 0) {
    return new Promise((resolve) => {
      // 非 Android 設備：直接允許所有地圖實例
      if (!this.isAndroidDevice) {
        const instanceId = ++this.instanceCounter
        this.activeInstances.set(componentId, { instanceId, priority })
        resolve({ allowed: true, instanceId })
        return
      }

      // Android 設備：應用實例限制
      if (this.activeInstances.size < this.maxInstances) {
        const instanceId = ++this.instanceCounter
        this.activeInstances.set(componentId, { instanceId, priority })
        resolve({ allowed: true, instanceId })
      } else {
        this.pendingQueue.push({ componentId, priority, resolve })
        this.pendingQueue.sort((a, b) => b.priority - a.priority)
        
        const lowestPriorityActive = this._findLowestPriorityActive()
        if (lowestPriorityActive && lowestPriorityActive.priority < priority) {
          this.releaseInstance(lowestPriorityActive.componentId)
        } else {
          resolve({ allowed: false, instanceId: null })
        }
      }
    })
  }

  releaseInstance(componentId) {
    if (this.activeInstances.has(componentId)) {
      this.activeInstances.delete(componentId)
      this._processQueue()
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

  _processQueue() {
    if (this.pendingQueue.length > 0 && this.activeInstances.size < this.maxInstances) {
      const next = this.pendingQueue.shift()
      const instanceId = ++this.instanceCounter
      this.activeInstances.set(next.componentId, { instanceId, priority: next.priority })
      next.resolve({ allowed: true, instanceId })
    }
  }

  getActiveCount() {
    return this.activeInstances.size
  }

  isActive(componentId) {
    return this.activeInstances.has(componentId)
  }
}

const mapInstanceManager = new MapInstanceManager(3)

export default mapInstanceManager
