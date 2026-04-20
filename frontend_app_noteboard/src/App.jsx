import { useState, useEffect, useRef } from 'react'
import { io } from 'socket.io-client'
import LocationMap from './LocationMap'
import LocationPicker from './LocationPicker'
import MapView from './MapView'
import TableView, { TABLE_CELL_RE } from './TableView'
import mapInstanceManager from './MapInstanceManager'

const DEFAULT_BOARD_ID = 'YourChannelName'
const APP_META = (typeof window !== 'undefined' && window.APP_META) ? window.APP_META : {}
const APP_SERVICE_NAME = APP_META.serviceName || 'Mesh資訊站'
const APP_PROJECT_NAME = APP_META.projectName || 'meshBridge/meshNoteboard'
const APP_VERSION = APP_META.version || '-'
const SEND_INTERVAL_SECOND = APP_META.sendIntervalSecond || 30

const COLOR_PALETTE = [
  'hsl(0, 70%, 85%)',      // 0: Red
  'hsl(30, 70%, 85%)',     // 1: Orange
  'hsl(60, 70%, 85%)',     // 2: Yellow
  'hsl(90, 70%, 85%)',     // 3: Light Green
  'hsl(120, 70%, 85%)',    // 4: Green
  'hsl(150, 70%, 85%)',    // 5: Teal
  'hsl(180, 70%, 85%)',    // 6: Cyan
  'hsl(210, 70%, 85%)',    // 7: Light Blue
  'hsl(240, 70%, 85%)',    // 8: Blue
  'hsl(270, 70%, 85%)',    // 9: Purple<span class="note-time">2025/12/29 (上午) 11:30</span>
  'hsl(300, 70%, 85%)',    // 10: Magenta
  'hsl(330, 70%, 85%)',    // 11: Pink
  'hsl(0, 0%, 85%)',       // 12: Light Gray
  'hsl(0, 0%, 75%)',       // 13: Gray
  'hsl(45, 80%, 85%)',     // 14: Gold
  'hsl(0, 0%, 100%)'       // 15: White
]

function randomCode8() {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  let out = '';
  for (let i = 0; i < 8; i++) out += alphabet[bytes[i] % 36];
  return out;
}

function generatePastelColor(str) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  const h = Math.abs(hash) % 360
  return {
    bg: `hsl(${h}, 70%, 85%)`,
    text: '#333'
  }
}

function getUTF8ByteLength(str) {
  return new Blob([str]).size
}

const MAX_BYTES = 150

function App() {
  const [socket, setSocket] = useState(null)
  const [notes, setNotes] = useState([])
  const [loraOnline, setLoraOnline] = useState(false)
  const [channelValidated, setChannelValidated] = useState(false)
  const [channelErrorMessage, setChannelErrorMessage] = useState(null)
  const [powerIssue, setPowerIssue] = useState(false)
  const [boardId, setBoardId] = useState(DEFAULT_BOARD_ID)
  const [activeChannels, setActiveChannels] = useState([])
  const [showChannelDropdown, setShowChannelDropdown] = useState(false)
  const [channelVerifiedStatus, setChannelVerifiedStatus] = useState({})
  const [showPasswordModal, setShowPasswordModal] = useState(false)
  const [pendingChannel, setPendingChannel] = useState(null)
  const [passwordInput, setPasswordInput] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [myUUID, setMyUUID] = useState('')
  const [isCreatingNote, setIsCreatingNote] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [draftColorIndex, setDraftColorIndex] = useState(0)
  const [editingNoteId, setEditingNoteId] = useState(null)
  const [editText, setEditText] = useState('')
  const [editColorIndex, setEditColorIndex] = useState(0)
  const [modalConfig, setModalConfig] = useState({ show: false, type: 'alert', title: '', message: '', onConfirm: null })
  const [colorPickerNote, setColorPickerNote] = useState(null)
  const [selectedColorIndex, setSelectedColorIndex] = useState(0)
  const [sortOrder, setSortOrder] = useState('newest')
  const [keywordFilter, setKeywordFilter] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [showTableCommands, setShowTableCommands] = useState(false)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [headerVisible, setHeaderVisible] = useState(true)
  const lastScrollY = useRef(0)
  const draftNoteRef = useRef(null)
  const draftTextareaRef = useRef(null)
  const [draftByteCount, setDraftByteCount] = useState(0)
  const [editByteCount, setEditByteCount] = useState(0)
  const [isComposing, setIsComposing] = useState(false)
  const [isReordering, setIsReordering] = useState(false)
  const prevSortOrder = useRef(sortOrder)
  const [isReplyingTo, setIsReplyingTo] = useState(null)
  const [replyText, setReplyText] = useState('')
  const [replyColorIndex, setReplyColorIndex] = useState(0)
  const [replyByteCount, setReplyByteCount] = useState(0)
  const replyTextareaRef = useRef(null)
  const [newlyCreatedNoteId, setNewlyCreatedNoteId] = useState(null)
  const noteRefs = useRef({})
  const [ackData, setAckData] = useState({})
  const [ackTooltip, setAckTooltip] = useState(null)
  const [ackTooltipPosition, setAckTooltipPosition] = useState({ top: 0, left: 0 })
  const ackTooltipRef = useRef(null)
  const ackCounterRefs = useRef({})
  const touchStartPos = useRef({ x: 0, y: 0 })
  const [senderTooltip, setSenderTooltip] = useState(null)
  const [senderTooltipPosition, setSenderTooltipPosition] = useState({ top: 0, left: 0 })
  const [senderTooltipData, setSenderTooltipData] = useState(null)
  const senderTooltipRef = useRef(null)
  const senderStatusRefs = useRef({})
  const [adminChannels, setAdminChannels] = useState([])
  const [showAdminModal, setShowAdminModal] = useState(false)
  const [adminPasscode, setAdminPasscode] = useState('')
  const [channelsPostPasscode, setChannelsPostPasscode] = useState({})
  const [draftPostPasscode, setDraftPostPasscode] = useState('')
  const [replyPostPasscode, setReplyPostPasscode] = useState('')
  const [showLocationPicker, setShowLocationPicker] = useState(false)
  const [userLastLocations, setUserLastLocations] = useState({})
  const [mapEnabled, setMapEnabled] = useState(false)
  const [filterInputReadonly, setFilterInputReadonly] = useState(true)
  const [reauthOnChannelSwitch, setReauthOnChannelSwitch] = useState(false)
  const filterInputRef = useRef(null)
  const channelSwitchRef = useRef(false)
  const boardViewMemory = useRef({})
  const [isSubmittingDraft, setIsSubmittingDraft] = useState(false)
  const [isSubmittingReply, setIsSubmittingReply] = useState(false)
  const [isSubmittingEdit, setIsSubmittingEdit] = useState(false)
  const [viewMode, setViewMode] = useState(() => {
    try { return sessionStorage.getItem('viewMode') || 'sticky' } catch { return 'sticky' }
  })
  const [globalLanOnlyCount, setGlobalLanOnlyCount] = useState(0)

  // 根據當前 boardId 判斷是否為該頻道的管理者
  const isAdmin = adminChannels.includes(boardId)
  // 根據當前 boardId 判斷是否需要張貼通關碼
  const postPasscodeRequired = channelsPostPasscode[boardId] || false

  useEffect(() => {
    const fetchUserLastLocation = async () => {
      if (!myUUID) return
      
      try {
        const response = await fetch(`/api/user/${myUUID}/last-location`)
        const data = await response.json()
        
        if (data.success && data.location) {
          setUserLastLocations(prev => ({
            ...prev,
            [myUUID]: data.location
          }))
        }
      } catch (error) {
        console.error('Failed to fetch user last location:', error)
      }
    }
    
    fetchUserLastLocation()
  }, [myUUID])

  const fetchGlobalLanOnlyCount = async () => {
    try {
      const response = await fetch('/api/global/lan-only-count')
      const data = await response.json()
      if (data.success) {
        setGlobalLanOnlyCount(data.count)
      }
    } catch (error) {
      console.error('Failed to fetch global LAN-only count:', error)
    }
  }

  const fetchNotes = async (includeDeleted = false, targetBoardId = null, autoSwitchView = false) => {
    try {
      const actualBoardId = targetBoardId || boardId
      const response = await fetch(`/api/boards/${actualBoardId}/notes?is_include_deleted=${includeDeleted}`)
      const data = await response.json()
      if (data.success) {
        setNotes(data.notes)
        fetchAllAcks(data.notes, actualBoardId)
        // Auto-switch view mode after channel switch
        if (autoSwitchView) {
          const remembered = boardViewMemory.current[actualBoardId]
          setViewMode(remembered || 'sticky')
        }
      }
    } catch (error) {
      console.error('Failed to fetch notes:', error)
    }
  }

  const fetchAllAcks = async (notesList, targetBoardId = null) => {
    const actualBoardId = targetBoardId || boardId
    const newAckData = {}
    
    const allNotes = []
    notesList.forEach(note => {
      allNotes.push(note)
      if (note.replyNotes) {
        allNotes.push(...note.replyNotes)
      }
    })
    
    for (const note of allNotes) {
      if (note.noteId) {
        try {
          const response = await fetch(`/api/boards/${actualBoardId}/notes/${note.noteId}/acks`)
          const data = await response.json()
          if (data.success) {
            newAckData[note.noteId] = data.acks
          }
        } catch (error) {
          console.error(`Failed to fetch ACKs for note ${note.noteId}:`, error)
        }
      }
    }
    
    setAckData(newAckData)
  }

  const fetchAckForNote = async (noteId) => {
    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${noteId}/acks`)
      const data = await response.json()
      if (data.success) {
        setAckData(prev => ({
          ...prev,
          [noteId]: data.acks
        }))
      }
    } catch (error) {
      console.error(`Failed to fetch ACKs for note ${noteId}:`, error)
    }
  }

  useEffect(() => {
    const initializeApp = async () => {
      // 從 localStorage 載入先前儲存的頻道清單
      try {
        const cachedChannels = localStorage.getItem('activeChannels')
        if (cachedChannels) {
          const parsedChannels = JSON.parse(cachedChannels)
          if (Array.isArray(parsedChannels) && parsedChannels.length > 0) {
            setActiveChannels(parsedChannels)
            console.log('已從快取載入頻道清單:', parsedChannels)
          }
        }
      } catch (error) {
        console.error('Failed to load cached channels:', error)
      }

      try {
        const response = await fetch('/api/user/uuid')
        const data = await response.json()
        if (data.success) {
          setMyUUID(data.uuid)
        } else {
          const fallbackUuid = randomCode8()
          setMyUUID(fallbackUuid)
        }
      } catch (error) {
        console.error('Failed to fetch UUID from backend:', error)
        const fallbackUuid = randomCode8()
        setMyUUID(fallbackUuid)
      }

      try {
        const adminResponse = await fetch('/api/user/admin/status', {
          credentials: 'include'
        })
        const adminData = await adminResponse.json()
        if (adminData.success && adminData.admin_channels) {
          setAdminChannels(adminData.admin_channels)
        }
      } catch (error) {
        console.error('Failed to fetch admin status:', error)
      }

      try {
        const passcodeResponse = await fetch('/api/config/post_passcode_required')
        const passcodeData = await passcodeResponse.json()
        if (passcodeData.success && passcodeData.channels_post_passcode) {
          setChannelsPostPasscode(passcodeData.channels_post_passcode)
        }
      } catch (error) {
        console.error('Failed to fetch post passcode config:', error)
      }

      try {
        const featuresResponse = await fetch('/api/config/features')
        const featuresData = await featuresResponse.json()
        if (featuresData.success && featuresData.features) {
          setMapEnabled(featuresData.features.map_enabled || false)
          setReauthOnChannelSwitch(featuresData.features.reauth_on_channel_switch || false)
        }
      } catch (error) {
        console.error('Failed to fetch features config:', error)
      }

      let initialBoard = null
      try {
        const currentBoardResponse = await fetch('/api/session/current_board')
        const currentBoardData = await currentBoardResponse.json()
        if (currentBoardData.success && currentBoardData.board_id) {
          initialBoard = currentBoardData.board_id
          setBoardId(initialBoard)
        }
      } catch (error) {
        console.error('Failed to fetch current board:', error)
      }

      let statusMap = {}
      try {
        const verifiedStatusResponse = await fetch('/api/channel/verified_status')
        const verifiedStatusData = await verifiedStatusResponse.json()
        if (verifiedStatusData.success && verifiedStatusData.channels) {
          verifiedStatusData.channels.forEach(ch => {
            statusMap[ch.name] = {
              requiresPassword: ch.requires_password,
              isVerified: ch.is_verified
            }
          })
          setChannelVerifiedStatus(statusMap)
        }
      } catch (error) {
        console.error('Failed to fetch verified status:', error)
      }

      // 檢查初始 board 是否需要密碼驗證
      if (initialBoard && statusMap[initialBoard]) {
        const boardStatus = statusMap[initialBoard]
        if (boardStatus.requiresPassword && !boardStatus.isVerified) {
          setPendingChannel(initialBoard)
          setPasswordInput('')
          setPasswordError('')
          setShowPasswordModal(true)
        }
      }

      fetchGlobalLanOnlyCount()

      const newSocket = io()
      setSocket(newSocket)

      newSocket.on('lora_status', (data) => {
        setLoraOnline(data.online)
        setChannelValidated(data.channel_validated !== false)
        setChannelErrorMessage(data.error_message || null)
        setPowerIssue(data.power_issue || false)
        
        // 只有當收到非空的 active_channels 時才更新
        // 當 LoRa 斷線時，後端會發送空陣列，但我們保留快取的頻道清單
        if (data.active_channels && data.active_channels.length > 0) {
          setActiveChannels(data.active_channels)
          setBoardId(prev => {
            // 只有當 prev 是預設值時，才切換到第一個 active channel
            // 這樣可以避免覆蓋從 session 載入的 board
            if (prev === DEFAULT_BOARD_ID && data.active_channels.length > 0) {
              return data.active_channels[0]
            }
            // 如果從 session 載入的 board 已不在可用頻道中，自動回到預設頻道
            if (prev !== DEFAULT_BOARD_ID && data.active_channels.length > 0 && !data.active_channels.includes(prev)) {
              console.log(`⚠️ 先前選擇的頻道 "${prev}" 已不在可用頻道中，自動切換至 "${data.active_channels[0]}"`)
              return data.active_channels[0]
            }
            return prev
          })
        } else if (data.active_channels && data.active_channels.length === 0) {
          // LoRa 斷線時收到空陣列，保留現有的 activeChannels（從快取載入的）
          console.log('LoRa 斷線，保留快取的頻道清單以供切換')
        }

        if (data.online && data.channel_validated === false) {
          console.log('⚠️ LoRa 已連線，但 Channel 名稱不符合設定')
          if (data.error_message) {
            console.log('   ' + data.error_message)
          }
        }
      })
    }

    initializeApp()

    return () => {
      if (socket) {
        socket.close()
      }
    }
  }, [])

  // 將 activeChannels 儲存到 localStorage，以便在 LoRa 斷線時仍可切換頻道
  useEffect(() => {
    if (activeChannels.length > 0) {
      try {
        localStorage.setItem('activeChannels', JSON.stringify(activeChannels))
        console.log('已儲存頻道清單到快取:', activeChannels)
      } catch (error) {
        console.error('Failed to cache channels:', error)
      }
    }
  }, [activeChannels])

  useEffect(() => {
    try { sessionStorage.setItem('viewMode', viewMode) } catch {}
  }, [viewMode])

  useEffect(() => {
    if (!showChannelDropdown) return
    const handleClickOutside = (e) => {
      if (!e.target.closest('.header-left')) {
        setShowChannelDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showChannelDropdown])

  useEffect(() => {
    if (!socket) return

    const handleRefreshNotes = (data) => {
      fetchNotes(showArchived, boardId)
      fetchGlobalLanOnlyCount()
    }

    const handleAckReceived = (data) => {
      if (data.note_id) {
        fetchAckForNote(data.note_id)
      }
    }

    const handleUsbConnectionError = (data) => {
      console.error('USB connection error:', data.message)
      setModalConfig({
        show: true,
        type: 'alert',
        title: '連線錯誤',
        message: data.message,
        onConfirm: () => setModalConfig(prev => ({ ...prev, show: false }))
      })
    }

    socket.on('refresh_notes', handleRefreshNotes)
    socket.on('ack_received', handleAckReceived)
    socket.on('usb_connection_error', handleUsbConnectionError)

    return () => {
      socket.off('refresh_notes', handleRefreshNotes)
      socket.off('ack_received', handleAckReceived)
      socket.off('usb_connection_error', handleUsbConnectionError)
    }
  }, [socket, showArchived, boardId])

  useEffect(() => {
    if (boardId !== DEFAULT_BOARD_ID) {
      const autoSwitchView = channelSwitchRef.current
      fetchNotes(showArchived, null, autoSwitchView)
      channelSwitchRef.current = false
    }
  }, [showArchived, boardId])

  useEffect(() => {
    if (prevSortOrder.current !== sortOrder) {
      setIsReordering(true)
      const timer = setTimeout(() => {
        setIsReordering(false)
      }, 600)
      prevSortOrder.current = sortOrder
      return () => clearTimeout(timer)
    }
  }, [sortOrder])

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (ackTooltip && ackTooltipRef.current && !ackTooltipRef.current.contains(event.target)) {
        const ackCounter = event.target.closest('.ack-counter')
        if (!ackCounter) {
          setAckTooltip(null)
        }
      }
    }

    if (ackTooltip) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [ackTooltip])

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (senderTooltip && senderTooltipRef.current && !senderTooltipRef.current.contains(event.target)) {
        const senderStatus = event.target.closest('.note-status.sender-clickable')
        if (!senderStatus) {
          setSenderTooltip(null)
          setSenderTooltipData(null)
        }
      }
    }

    if (senderTooltip) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [senderTooltip])

  useEffect(() => {
    const handleScroll = () => {
      // 只在手機版（螢幕寬度 <= 768px）啟用 header 自動隱藏
      if (window.innerWidth > 768) {
        setHeaderVisible(true)
        return
      }

      const currentScrollY = window.scrollY
      const scrollDiff = currentScrollY - lastScrollY.current
      
      // 檢查是否接近底部（防止 overscroll 誤觸發）
      const documentHeight = document.documentElement.scrollHeight
      const windowHeight = window.innerHeight
      const isNearBottom = (currentScrollY + windowHeight) >= (documentHeight - 50)
      
      if (currentScrollY < 10) {
        setHeaderVisible(true)
      } else if (scrollDiff > 5 && currentScrollY > 50 && !isNearBottom) {
        // 向下滾動且不在底部時隱藏 header
        setHeaderVisible(false)
      } else if (scrollDiff < -5 && !isNearBottom) {
        // 向上滾動且不在底部時顯示 header
        setHeaderVisible(true)
      }
      
      lastScrollY.current = currentScrollY
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (isCreatingNote && draftTextareaRef.current) {
      setTimeout(() => {
        if (draftTextareaRef.current) {
          const textareaRect = draftTextareaRef.current.getBoundingClientRect()
          const currentScrollY = window.scrollY
          const targetScrollY = currentScrollY + textareaRect.top - 100
          
          window.scrollTo({
            top: targetScrollY,
            behavior: 'smooth'
          })
          
          draftTextareaRef.current.focus()
          // If text is pre-filled (e.g. from map), move cursor to beginning
          if (draftTextareaRef.current.value) {
            draftTextareaRef.current.setSelectionRange(0, 0)
          }
        }
      }, 150)
    }
  }, [isCreatingNote])

  useEffect(() => {
    if (newlyCreatedNoteId) {
      let scrollCompleted = false
      
      const scrollToNote = () => {
        const noteElement = noteRefs.current[newlyCreatedNoteId]
        if (noteElement && !scrollCompleted) {
          const noteRect = noteElement.getBoundingClientRect()
          const currentScrollY = window.scrollY
          const targetScrollY = currentScrollY + noteRect.top - 100
          
          window.scrollTo({
            top: targetScrollY,
            behavior: 'smooth'
          })
          
          scrollCompleted = true
          
          // 捲動完成後才加上動畫 class
          setTimeout(() => {
            if (noteElement) {
              noteElement.classList.add('note-paste-animation')
            }
          }, 500) // 等待捲動動畫完成（smooth scroll 大約需要 300-500ms）
          
          return true
        }
        return false
      }

      // 嘗試多次捲動，確保 DOM 已更新
      let attempts = 0
      const maxAttempts = 10
      const scrollInterval = setInterval(() => {
        attempts++
        if (scrollToNote() || attempts >= maxAttempts) {
          clearInterval(scrollInterval)
        }
      }, 100)

      const clearTimer = setTimeout(() => {
        setNewlyCreatedNoteId(null)
      }, 3000) // 延長清除時間，確保動畫完整播放

      return () => {
        clearInterval(scrollInterval)
        clearTimeout(clearTimer)
      }
    }
  }, [newlyCreatedNoteId, notes])


  const showAlert = (message, title = '提示') => {
    setModalConfig({
      show: true,
      type: 'alert',
      title,
      message,
      onConfirm: () => setModalConfig({ ...modalConfig, show: false })
    })
  }

  const showConfirm = (message, title = '確認') => {
    return new Promise((resolve) => {
      setModalConfig({
        show: true,
        type: 'confirm',
        title,
        message,
        onConfirm: () => {
          setModalConfig({ ...modalConfig, show: false })
          resolve(true)
        },
        onCancel: () => {
          setModalConfig({ ...modalConfig, show: false })
          resolve(false)
        }
      })
    })
  }

  const handleUserRoleClick = async () => {
    if (!isAdmin) {
      setShowAdminModal(true)
      setAdminPasscode('')
    } else {
      const confirmed = await showConfirm(`確定要登出頻道 "${boardId}" 的管理者身份，切換為一般使用者嗎？`, '登出管理者')
      if (confirmed) {
        handleAdminLogout()
      }
    }
  }

  const handleAdminAuthenticate = async () => {
    if (!adminPasscode.trim()) {
      showAlert('請輸入管理者密碼！')
      return
    }

    try {
      const response = await fetch('/api/user/admin/authenticate', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          passcode: adminPasscode,
          board_id: boardId
        })
      })

      const data = await response.json()
      if (data.success && data.is_admin) {
        setAdminChannels(prev => prev.includes(boardId) ? prev : [...prev, boardId])
        setShowAdminModal(false)
        setAdminPasscode('')
        showAlert(`已切換至頻道 "${boardId}" 的管理者身份`, '成功')
      } else {
        showAlert('密碼錯誤，請重新輸入', '錯誤')
        setAdminPasscode('')
      }
    } catch (error) {
      console.error('Failed to authenticate admin:', error)
      showAlert('認證失敗：' + error.message, '錯誤')
    }
  }

  const handleCloseAdminModal = () => {
    setShowAdminModal(false)
    setAdminPasscode('')
  }

  const handleAdminLogout = async () => {
    try {
      const response = await fetch('/api/user/admin/logout', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          board_id: boardId
        })
      })

      const data = await response.json()
      if (data.success) {
        setAdminChannels(prev => prev.filter(ch => ch !== boardId))
        showAlert(`已登出頻道 "${boardId}" 的管理者身份`, '成功')
      } else {
        showAlert('登出失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to logout admin:', error)
      showAlert('登出失敗：' + error.message, '錯誤')
    }
  }

  const handlePinNote = async (noteId) => {
    const confirmed = await showConfirm('是否將此便利貼置頂？一次僅能有一則置頂。', '置頂便利貼')
    if (!confirmed) {
      return
    }

    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${noteId}/pin`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      })

      const data = await response.json()
      if (data.success) {
        showAlert('已成功置頂便利貼', '成功')
      } else {
        showAlert('置頂失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to pin note:', error)
      showAlert('置頂失敗：' + error.message, '錯誤')
    }
  }

  const handleResendPin = async (noteId) => {
    const confirmed = await showConfirm('確認重新發送置頂指令？', '重送置頂')
    if (!confirmed) {
      return
    }

    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${noteId}/pin`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      })

      const data = await response.json()
      if (data.success) {
        showAlert('已重新發送置頂指令', '成功')
      } else {
        showAlert('重送置頂失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to resend pin:', error)
      showAlert('重送置頂失敗：' + error.message, '錯誤')
    }
  }

  const deleteNote = async (index) => {
    const newNotes = notes.filter((_, i) => i !== index)
    setNotes(newNotes)
  }

  const handleCreateNote = (initialText) => {
    const text = (typeof initialText === 'string') ? initialText : ''
    setIsCreatingNote(true)
    setDraftText(text)
    setDraftColorIndex(0)
    setDraftByteCount(getUTF8ByteLength(text))
    setDraftPostPasscode('')
  }

  const handleCancelDraft = () => {
    setIsCreatingNote(false)
    setDraftText('')
    setDraftColorIndex(0)
    setDraftByteCount(0)
    setDraftPostPasscode('')
  }

  const handleCreateReply = (parentNoteId) => {
    setIsReplyingTo(parentNoteId)
    setReplyText('')
    setReplyColorIndex(0)
    setReplyByteCount(0)
    setReplyPostPasscode('')
  }

  const saveBoardView = () => {
    boardViewMemory.current[boardId] = viewMode
  }

  const handleChannelSwitch = async (channelName) => {
    if (isCreatingNote) handleCancelDraft()
    if (isReplyingTo) handleCancelReply()

    const status = channelVerifiedStatus[channelName]
    
    if (status && status.requiresPassword && !status.isVerified) {
      // 若啟用 reauth，先對後端發 select_board 以清除舊頻道認證
      if (reauthOnChannelSwitch && boardId !== channelName) {
        try {
          await fetch('/api/session/select_board', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board_id: channelName })
          })
        } catch (e) { /* ignore */ }
        // 同步更新前端：舊頻道標記為未驗證、移除 admin
        setChannelVerifiedStatus(prev => {
          const oldStatus = prev[boardId]
          if (oldStatus && oldStatus.requiresPassword) {
            return { ...prev, [boardId]: { ...oldStatus, isVerified: false } }
          }
          return prev
        })
        setAdminChannels(prev => prev.filter(ch => ch !== boardId))
      }
      saveBoardView()
      setPendingChannel(channelName)
      setPasswordInput('')
      setPasswordError('')
      setShowPasswordModal(true)
      setShowChannelDropdown(false)
      return
    }
    
    try {
      const oldBoardId = boardId
      const response = await fetch('/api/session/select_board', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board_id: channelName })
      })
      const data = await response.json()
      if (data.success) {
        // 若啟用 reauth，同步清除前端舊頻道的認證狀態
        if (reauthOnChannelSwitch && oldBoardId !== channelName) {
          setChannelVerifiedStatus(prev => {
            const oldStatus = prev[oldBoardId]
            if (oldStatus && oldStatus.requiresPassword) {
              return { ...prev, [oldBoardId]: { ...oldStatus, isVerified: false } }
            }
            return prev
          })
          setAdminChannels(prev => prev.filter(ch => ch !== oldBoardId))
        }
        saveBoardView()
        channelSwitchRef.current = true
        setBoardId(channelName)
        setShowChannelDropdown(false)
      }
    } catch (error) {
      console.error('Failed to switch channel:', error)
    }
  }

  const handlePasswordSubmit = async () => {
    if (!pendingChannel) return
    
    setPasswordError('')
    
    try {
      const response = await fetch('/api/channel/verify_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          channel_name: pendingChannel,
          password: passwordInput 
        })
      })
      const data = await response.json()
      
      if (data.success && data.verified) {
        setChannelVerifiedStatus(prev => ({
          ...prev,
          [pendingChannel]: {
            ...prev[pendingChannel],
            isVerified: true
          }
        }))
        
        const selectResponse = await fetch('/api/session/select_board', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ board_id: pendingChannel })
        })
        const selectData = await selectResponse.json()
        if (selectData.success) {
          const verifiedChannel = pendingChannel
          saveBoardView()
          channelSwitchRef.current = true
          setBoardId(verifiedChannel)
          setShowPasswordModal(false)
          setPendingChannel(null)
          setPasswordInput('')
        }
      } else {
        setPasswordError('密碼錯誤，請重試')
      }
    } catch (error) {
      console.error('Failed to verify password:', error)
      setPasswordError('驗證失敗，請重試')
    }
  }

  const handlePasswordCancel = () => {
    setShowPasswordModal(false)
    setPendingChannel(null)
    setPasswordInput('')
    setPasswordError('')
  }

  const handleCancelReply = () => {
    setIsReplyingTo(null)
    setReplyText('')
    setReplyColorIndex(0)
    setReplyByteCount(0)
    setReplyPostPasscode('')
  }

  const handleSubmitReply = async () => {
    const text = replyText.trim()
    if (!text) {
      showAlert('請輸入回覆內容！')
      return
    }

    // 非管理者且需要通關碼時，檢查是否已填寫
    if (!isAdmin && postPasscodeRequired && !replyPostPasscode.trim()) {
      showAlert('請輸入發送用通關碼！')
      return
    }

    if (isSubmittingReply) {
      return
    }

    setIsSubmittingReply(true)
    try {
      const response = await fetch(`/api/boards/${boardId}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: text,
          author_key: myUUID,
          color_index: replyColorIndex,
          parent_note_id: isReplyingTo,
          post_passcode: replyPostPasscode
        })
      })

      const data = await response.json()
      if (data.success) {
        setIsReplyingTo(null)
        setReplyText('')
        setReplyColorIndex(0)
        setReplyByteCount(0)
        setReplyPostPasscode('')
        
        if (data.note && data.note.noteId) {
          setNewlyCreatedNoteId(data.note.noteId)
        }
      } else {
        showAlert('張貼回覆失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to create reply:', error)
      showAlert('張貼回覆失敗：' + error.message, '錯誤')
    } finally {
      setIsSubmittingReply(false)
    }
  }

  const handleReplyTextChange = (e) => {
    const newText = e.target.value
    const byteLength = getUTF8ByteLength(newText)
    
    if (!isComposing && byteLength > MAX_BYTES) {
      return
    }
    
    setReplyText(newText)
    setReplyByteCount(byteLength)
  }

  const handleSubmitDraft = async () => {
    const text = draftText.trim()
    if (!text) {
      showAlert('請輸入便利貼內容！')
      return
    }

    // 非管理者且需要通關碼時，檢查是否已填寫
    if (!isAdmin && postPasscodeRequired && !draftPostPasscode.trim()) {
      showAlert('請輸入發送用通關碼！')
      return
    }

    if (isSubmittingDraft) {
      return
    }

    setIsSubmittingDraft(true)
    try {
      const response = await fetch(`/api/boards/${boardId}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: text,
          author_key: myUUID,
          color_index: draftColorIndex,
          post_passcode: draftPostPasscode
        })
      })

      const data = await response.json()
      if (data.success) {
        setIsCreatingNote(false)
        setDraftText('')
        setDraftColorIndex(0)
        setDraftByteCount(0)
        setDraftPostPasscode('')
        
        if (data.note && data.note.noteId) {
          setNewlyCreatedNoteId(data.note.noteId)
        }
      } else {
        showAlert('建立便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to create note:', error)
      showAlert('建立便利貼失敗：' + error.message, '錯誤')
    } finally {
      setIsSubmittingDraft(false)
    }
  }

  const handleEditNote = (note) => {
    setEditingNoteId(note.noteId)
    setEditText(note.text)
    setEditByteCount(getUTF8ByteLength(note.text))
    const colorIndex = COLOR_PALETTE.findIndex(c => c === note.bgColor)
    setEditColorIndex(colorIndex >= 0 ? colorIndex : 0)
  }

  const handleCancelEdit = () => {
    setEditingNoteId(null)
    setEditText('')
    setEditColorIndex(0)
    setEditByteCount(0)
  }

  const handleSubmitEdit = async (noteId) => {
    const text = editText.trim()
    if (!text) {
      showAlert('請輸入便利貼內容！')
      return
    }

    if (isSubmittingEdit) {
      return
    }

    setIsSubmittingEdit(true)
    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${noteId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: text,
          author_key: myUUID,
          color_index: editColorIndex
        })
      })

      const data = await response.json()
      if (data.success) {
        setEditingNoteId(null)
        setEditText('')
        setEditColorIndex(0)
        setEditByteCount(0)
      } else {
        showAlert('更新便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to update note:', error)
      showAlert('更新便利貼失敗：' + error.message, '錯誤')
    } finally {
      setIsSubmittingEdit(false)
    }
  }

  const handleDeleteNote = async (noteId, isLanOnly = false, authorKey = null) => {
    // 找到要刪除的 note，檢查是否為 root 節點
    // root note 是在 notes 陣列中的，reply note 是在 note.replyNotes 中的
    let isRootNote = false
    let noteToDelete = notes.find(n => n.noteId === noteId)
    
    if (noteToDelete) {
      // 找到了，這是一個 root note
      isRootNote = true
    } else {
      // 沒找到，可能是 reply note，在某個 note 的 replyNotes 中
      for (const note of notes) {
        if (note.replyNotes) {
          noteToDelete = note.replyNotes.find(r => r.noteId === noteId)
          if (noteToDelete) {
            isRootNote = false
            break
          }
        }
      }
    }
    
    // 如果是 root 節點，增加警告訊息
    let confirmMessage = '確定要封存這個便利貼嗎？'
    if (isRootNote) {
      confirmMessage += '\n\n⚠️ 會自動連帶隱藏整串便利貼內容'
    }
    
    const confirmed = await showConfirm(confirmMessage, '確認封存')
    if (!confirmed) {
      return
    }

    // 如果是管理者刪除他人的 note，使用該 note 的 author_key
    const effectiveAuthorKey = authorKey || myUUID

    try {
      let response
      if (isLanOnly) {
        response = await fetch(`/api/boards/${boardId}/notes/${noteId}`, {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            author_key: effectiveAuthorKey
          })
        })
      } else {
        response = await fetch(`/api/boards/${boardId}/notes/${noteId}/archive`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            author_key: effectiveAuthorKey,
            is_admin: isAdmin && authorKey !== null
          })
        })
      }

      const data = await response.json()
      if (!data.success) {
        showAlert('封存便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
      showAlert('封存便利貼失敗：' + error.message, '錯誤')
    }
  }

  const handleArchiveNote = async (noteId) => {
    return handleDeleteNote(noteId, false)
  }

  const handleResendNote = async (noteId, noteAuthorKey = null) => {
    const confirmed = await showConfirm('確認重新發送訊息？', '重新發送')
    if (!confirmed) {
      return
    }

    // 判斷是否為管理者重新發送他人的 note
    const isAdminResend = isAdmin && noteAuthorKey && noteAuthorKey !== myUUID

    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${noteId}/resend`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          author_key: myUUID,
          is_admin: isAdminResend
        })
      })

      const data = await response.json()
      if (data.success) {
        showAlert(`已重新發送訊息 (第 ${data.resent_count} 次)`, '成功')
      } else {
        showAlert('重新發送失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to resend note:', error)
      showAlert('重新發送失敗：' + error.message, '錯誤')
    }
  }

  const handleOpenColorPicker = (note) => {
    const colorIndex = COLOR_PALETTE.findIndex(c => c === note.bgColor)
    setSelectedColorIndex(colorIndex >= 0 ? colorIndex : 0)
    setColorPickerNote(note)
  }

  const handleCloseColorPicker = () => {
    setColorPickerNote(null)
    setSelectedColorIndex(0)
  }

  const handleSubmitColorChange = async () => {
    if (!colorPickerNote) return

    // 判斷是否為管理者變更他人的 note 顏色
    const isMyNote = colorPickerNote.userId === myUUID
    const isAdminAction = isAdmin && !isMyNote

    try {
      const response = await fetch(`/api/boards/${boardId}/notes/${colorPickerNote.noteId}/color`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          author_key: myUUID,
          color_index: selectedColorIndex,
          is_admin: isAdminAction
        })
      })

      const data = await response.json()
      if (data.success) {
        handleCloseColorPicker()
      } else {
        showAlert('變更顏色失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to change color:', error)
      showAlert('變更顏色失敗：' + error.message, '錯誤')
    }
  }

  const getStatusDisplay = (status) => {
    switch (status) {
      case 'LoRa received':
        return 'LoRa接收'
      case 'sent':
      case 'LoRa sent':
        return 'LoRa送出'
      case 'local':
        return '⚠️ 僅區網'
      case 'LAN only':
        return '⚠️ 僅區網'
      default:
        return status
    }
  }

  const getFilteredAndSortedNotes = () => {
    let filtered = notes.filter(note => {
      if (!showTableCommands) {
        const trimmed = (note.text || '').trim()
        if (TABLE_CELL_RE.test(trimmed) || /^\{[a-z0-9]{6}:delete\}$/.test(trimmed)) {
          return false
        }
      }

      if (keywordFilter.trim()) {
        const keyword = keywordFilter.toLowerCase()
        const parentText = (note.text || '').toLowerCase()
        const parentSender = (note.sender || '').toLowerCase()
        
        if (parentText.includes(keyword) || parentSender.includes(keyword)) {
          return true
        }
        
        const replyNotes = note.replyNotes || []
        const hasMatchingReply = replyNotes.some(reply => {
          const replyText = (reply.text || '').toLowerCase()
          const replySender = (reply.sender || '').toLowerCase()
          return replyText.includes(keyword) || replySender.includes(keyword)
        })
        
        return hasMatchingReply
      }
      
      return true
    })

    const sorted = [...filtered].sort((a, b) => {
      // 置頂的便利貼永遠排在最前面
      if (a.isPinedNote && !b.isPinedNote) return -1
      if (!a.isPinedNote && b.isPinedNote) return 1
      
      // 如果都是置頂或都不是置頂，則按照選擇的排序方式排序
      if (sortOrder === 'newest') {
        return new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
      } else if (sortOrder === 'oldest') {
        return new Date(a.timestamp || 0) - new Date(b.timestamp || 0)
      } else if (sortOrder === 'color') {
        const colorA = COLOR_PALETTE.indexOf(a.bgColor)
        const colorB = COLOR_PALETTE.indexOf(b.bgColor)
        return colorA - colorB
      }
      return 0
    })

    return sorted
  }

  const handleDraftTextChange = (e) => {
    const newText = e.target.value
    const byteLength = getUTF8ByteLength(newText)
    
    if (!isComposing && byteLength > MAX_BYTES) {
      return
    }
    
    setDraftText(newText)
    setDraftByteCount(byteLength)
  }

  const handleEditTextChange = (e) => {
    const newText = e.target.value
    const byteLength = getUTF8ByteLength(newText)
    
    if (!isComposing && byteLength > MAX_BYTES) {
      return
    }
    
    setEditText(newText)
    setEditByteCount(byteLength)
  }

  const handleCompositionStart = () => {
    setIsComposing(true)
  }

  const handleCompositionEnd = (e, isEdit = false) => {
    setIsComposing(false)
    const newText = e.target.value
    const byteLength = getUTF8ByteLength(newText)
    
    if (byteLength > MAX_BYTES) {
      let truncatedText = newText
      while (getUTF8ByteLength(truncatedText) > MAX_BYTES) {
        truncatedText = truncatedText.slice(0, -1)
      }
      
      if (isEdit) {
        setEditText(truncatedText)
        setEditByteCount(getUTF8ByteLength(truncatedText))
      } else {
        setDraftText(truncatedText)
        setDraftByteCount(getUTF8ByteLength(truncatedText))
      }
    }
  }

  const handleOpenLocationPicker = () => {
    setShowLocationPicker(true)
  }

  const handleCloseLocationPicker = () => {
    setShowLocationPicker(false)
  }

  const saveUserLastLocation = async (mapState) => {
    if (!mapState || !myUUID) return
    
    try {
      await fetch(`/api/user/${myUUID}/last-location`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          lat: mapState.center.lat,
          lng: mapState.center.lng,
          zoom: mapState.zoom
        })
      })
      
      setUserLastLocations(prev => ({
        ...prev,
        [myUUID]: {
          lat: mapState.center.lat,
          lng: mapState.center.lng,
          zoom: mapState.zoom
        }
      }))
    } catch (error) {
      console.error('Failed to save user last location:', error)
    }
  }

  const handleLocationConfirm = (coordinateString, mapState) => {
    const locationRegex = /([\u4e00-\u9fa5a-zA-Z0-9_\-]+)?@\(([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\)/g
    
    if (editingNoteId) {
      const currentText = editText
      const textWithoutCoords = currentText.replace(locationRegex, '').trim()
      const newText = textWithoutCoords ? `${textWithoutCoords} ${coordinateString}` : coordinateString
      const byteLength = getUTF8ByteLength(newText)
      
      if (byteLength <= MAX_BYTES) {
        setEditText(newText)
        setEditByteCount(byteLength)
        setShowLocationPicker(false)
        
        saveUserLastLocation(mapState)
        
        if (draftTextareaRef.current) {
          draftTextareaRef.current.focus()
        }
      } else {
        showAlert('加入座標後會超過字數限制！', '錯誤')
      }
    } else if (isReplyingTo) {
      const currentText = replyText
      const textWithoutCoords = currentText.replace(locationRegex, '').trim()
      const newText = textWithoutCoords ? `${textWithoutCoords} ${coordinateString}` : coordinateString
      const byteLength = getUTF8ByteLength(newText)
      
      if (byteLength <= MAX_BYTES) {
        setReplyText(newText)
        setReplyByteCount(byteLength)
        setShowLocationPicker(false)
        
        saveUserLastLocation(mapState)
        
        if (replyTextareaRef.current) {
          replyTextareaRef.current.focus()
        }
      } else {
        showAlert('加入座標後會超過字數限制！', '錯誤')
      }
    } else {
      const currentText = draftText
      const textWithoutCoords = currentText.replace(locationRegex, '').trim()
      const newText = textWithoutCoords ? `${textWithoutCoords} ${coordinateString}` : coordinateString
      const byteLength = getUTF8ByteLength(newText)
      
      if (byteLength <= MAX_BYTES) {
        setDraftText(newText)
        setDraftByteCount(byteLength)
        setShowLocationPicker(false)
        
        saveUserLastLocation(mapState)
        
        if (draftTextareaRef.current) {
          draftTextareaRef.current.focus()
        }
      } else {
        showAlert('加入座標後會超過字數限制！', '錯誤')
      }
    }
  }

  const parseLocationsFromText = (text) => {
    const locationRegex = /([\u4e00-\u9fa5a-zA-Z0-9_\-]+)?@\(([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\)/g
    const locations = []
    let match
    
    while ((match = locationRegex.exec(text)) !== null) {
      const location = {
        lat: parseFloat(match[2]),
        lng: parseFloat(match[3])
      }
      
      if (match[1] && match[1].trim()) {
        location.label = match[1].trim()
      }
      
      locations.push(location)
    }
    
    return locations.length > 0 ? locations : null
  }

  const highlightText = (text, keyword) => {
    if (!keyword.trim()) {
      return text
    }

    const lowerText = text.toLowerCase()
    const lowerKeyword = keyword.toLowerCase()
    const parts = []
    let lastIndex = 0

    let index = lowerText.indexOf(lowerKeyword)
    while (index !== -1) {
      if (index > lastIndex) {
        parts.push(text.substring(lastIndex, index))
      }
      parts.push(
        <mark key={`${index}-${lastIndex}`} style={{ backgroundColor: 'yellow', color: '#333' }}>
          {text.substring(index, index + keyword.length)}
        </mark>
      )
      lastIndex = index + keyword.length
      index = lowerText.indexOf(lowerKeyword, lastIndex)
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex))
    }

    return parts.length > 0 ? parts : text
  }

  const renderNote = (data, index, isReply = false) => {
    const senderName = data.sender || 'Unknown'
    const senderID = data.userId || 'unknown-id'
    const text = data.text
    const time = data.time || ''
    const status = data.status || 'local'
    const bgColor = data.bgColor || generatePastelColor(senderID).bg

    const isMyNote = senderID === myUUID
    const canEdit = isMyNote && status === 'LAN only' && !data.archived
    const canManage = isMyNote && status !== 'LAN only' && !data.archived
    const canAdminDelete = isAdmin && !isMyNote && !data.archived && status !== 'LAN only'
    const trimmedText = (text || '').trim()
    const isTableCommand = TABLE_CELL_RE.test(trimmedText) || /^\{[a-z0-9]{6}:delete\}$/.test(trimmedText)
    const isEditing = editingNoteId === data.noteId

    if (isEditing) {
      return (
        <div 
          key={data.noteId || index} 
          className="sticky-note draft-note"
          style={{
            backgroundColor: COLOR_PALETTE[editColorIndex],
            color: '#333'
          }}
        >
          <div className="draft-header">編輯便利貼</div>
          <textarea
            className="draft-textarea"
            value={editText}
            onChange={handleEditTextChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={(e) => handleCompositionEnd(e, true)}
            placeholder="輸入內容..."
            autoFocus
          />
          {mapEnabled && (
            <div className="draft-tools">
              <button 
                className="btn-location-picker"
                onClick={handleOpenLocationPicker}
                title="地圖座標"
              >
                📍 地圖座標
              </button>
            </div>
          )}
          <div className="byte-counter-container">
            <div className="byte-counter-bar">
              <div 
                className="byte-counter-fill"
                style={{ 
                  width: `${Math.min((editByteCount / MAX_BYTES) * 100, 100)}%`,
                  backgroundColor: editByteCount > MAX_BYTES ? '#d32f2f' : '#3498db'
                }}
              />
            </div>
            <div className="byte-counter-text" style={{ color: editByteCount > MAX_BYTES ? '#d32f2f' : '#666' }}>
              {editByteCount}/{MAX_BYTES}
            </div>
          </div>
          <div className="color-picker">
            {COLOR_PALETTE.map((color, index) => (
              <div
                key={index}
                className={`color-option ${editColorIndex === index ? 'selected' : ''}`}
                style={{ backgroundColor: color }}
                onClick={() => setEditColorIndex(index)}
              />
            ))}
          </div>
          <div className="draft-actions">
            <button className="btn-cancel" onClick={handleCancelEdit}>取消</button>
            <button className="btn-submit" onClick={() => handleSubmitEdit(data.noteId)} disabled={isSubmittingEdit}>更新</button>
          </div>
        </div>
      )
    }

    return (
      <div 
        key={data.noteId || index} 
        ref={(el) => {
          if (data.noteId) {
            noteRefs.current[data.noteId] = el
          }
        }}
        className={`sticky-note ${status === 'local' ? 'note-failed' : ''} ${isReordering ? 'reordering' : ''} ${isReply ? 'reply-note' : ''}`}
        style={{
          backgroundColor: bgColor,
          color: '#333'
        }}
      >
        {(data.archived || data.isTempParentNote || data.isPinedNote) && (
          <div className="note-label">
            {data.archived ? '已封存' : data.isPinedNote ? '置頂' : '暫無法取得前張便利貼'}
          </div>
        )}
        <div className="note-content">{highlightText(text, keywordFilter)}</div>
        {mapEnabled && parseLocationsFromText(text) && (
          <div style={{ marginTop: '10px', marginBottom: '10px' }}>
            <LocationMap locations={parseLocationsFromText(text)} />
          </div>
        )}
        <div className="note-footer">
          <span className="note-time">{time}</span>
          <span className="note-footer-right">
            {(status === 'sent' || status === 'LoRa sent') && (data.userId === myUUID || isAdmin) && !data.archived ? (
              <span 
                className="note-status clickable"
                onClick={(e) => {
                  e.stopPropagation()
                  handleResendNote(data.noteId, data.userId)
                }}
                title="點擊重新發送"
              >
                {getStatusDisplay(status)}
                <span className="ack-counter-wrapper">
                  <span 
                    ref={(el) => {
                      if (data.noteId) {
                        ackCounterRefs.current[data.noteId] = el
                      }
                    }}
                    className="ack-counter"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (ackTooltip === data.noteId) {
                        setAckTooltip(null)
                      } else {
                        const rect = e.currentTarget.getBoundingClientRect()
                        setAckTooltipPosition({
                          top: rect.bottom + 8,
                          left: rect.right - 150
                        })
                        setAckTooltip(data.noteId)
                      }
                    }}
                  >
                    {(ackData[data.noteId] && ackData[data.noteId].length) || '-'}
                  </span>
                  <span
                    className="ack-counter-touch-overlay"
                    onTouchStart={(e) => {
                      touchStartPos.current = {
                        x: e.touches[0].clientX,
                        y: e.touches[0].clientY
                      }
                    }}
                    onTouchEnd={(e) => {
                      const touchEndX = e.changedTouches[0].clientX
                      const touchEndY = e.changedTouches[0].clientY
                      const deltaX = Math.abs(touchEndX - touchStartPos.current.x)
                      const deltaY = Math.abs(touchEndY - touchStartPos.current.y)
                      
                      if (deltaX < 10 && deltaY < 10) {
                        e.preventDefault()
                        e.stopPropagation()
                        if (ackTooltip === data.noteId) {
                          setAckTooltip(null)
                        } else {
                          const rect = ackCounterRefs.current[data.noteId].getBoundingClientRect()
                          setAckTooltipPosition({
                            top: rect.bottom + 8,
                            left: rect.right - 150
                          })
                          setAckTooltip(data.noteId)
                        }
                      }
                    }}
                  />
                </span>
              </span>
            ) : (status === 'sent' || status === 'LoRa sent') ? (
              <span className="note-status">
                {getStatusDisplay(status)}
                <span className="ack-counter-wrapper">
                  <span 
                    ref={(el) => {
                      if (data.noteId) {
                        ackCounterRefs.current[data.noteId] = el
                      }
                    }}
                    className="ack-counter"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (ackTooltip === data.noteId) {
                        setAckTooltip(null)
                      } else {
                        const rect = e.currentTarget.getBoundingClientRect()
                        setAckTooltipPosition({
                          top: rect.bottom + 8,
                          left: rect.right - 150
                        })
                        setAckTooltip(data.noteId)
                      }
                    }}
                  >
                    {(ackData[data.noteId] && ackData[data.noteId].length) || '-'}
                  </span>
                  <span
                    className="ack-counter-touch-overlay"
                    onTouchStart={(e) => {
                      touchStartPos.current = {
                        x: e.touches[0].clientX,
                        y: e.touches[0].clientY
                      }
                    }}
                    onTouchEnd={(e) => {
                      const touchEndX = e.changedTouches[0].clientX
                      const touchEndY = e.changedTouches[0].clientY
                      const deltaX = Math.abs(touchEndX - touchStartPos.current.x)
                      const deltaY = Math.abs(touchEndY - touchStartPos.current.y)
                      
                      if (deltaX < 10 && deltaY < 10) {
                        e.preventDefault()
                        e.stopPropagation()
                        if (ackTooltip === data.noteId) {
                          setAckTooltip(null)
                        } else {
                          const rect = ackCounterRefs.current[data.noteId].getBoundingClientRect()
                          setAckTooltipPosition({
                            top: rect.bottom + 8,
                            left: rect.right - 150
                          })
                          setAckTooltip(data.noteId)
                        }
                      }
                    }}
                  />
                </span>
              </span>
            ) : status === 'LoRa received' && data.senderNodeDisplay ? (
              <span 
                ref={(el) => {
                  if (data.noteId) {
                    senderStatusRefs.current[data.noteId] = el
                  }
                }}
                className="note-status sender-clickable"
                onClick={(e) => {
                  e.stopPropagation()
                  if (senderTooltip === data.noteId) {
                    setSenderTooltip(null)
                    setSenderTooltipData(null)
                  } else {
                    const rect = e.currentTarget.getBoundingClientRect()
                    setSenderTooltipPosition({
                      top: rect.bottom + 8,
                      left: rect.right - 150
                    })
                    setSenderTooltip(data.noteId)
                    setSenderTooltipData(data)
                  }
                }}
              >
                {getStatusDisplay(status)}
              </span>
            ) : (
              <span className="note-status">
                {getStatusDisplay(status)}
              </span>
            )}
          </span>
        </div>
        {canEdit && (
          <div className="note-actions">
            <button className="btn-edit" onClick={() => handleEditNote(data)}>✏️</button>
            <button className="btn-delete" onClick={() => handleDeleteNote(data.noteId, true)}>🗑️</button>
          </div>
        )}
        {canManage && (
          <div className="note-actions">
            <button className="btn-delete" onClick={() => handleDeleteNote(data.noteId, false)}>🗑️</button>
            <button className="btn-color" onClick={() => handleOpenColorPicker(data)}>🎨</button>
            {isAdmin && !isReply && !data.replyLoraMessageId && !data.isTempParentNote && !data.archived && data.status !== 'Sending' && !isTableCommand && (
              data.isPinedNote ? (
                <button className="btn-resend-pin" onClick={() => handleResendPin(data.noteId)} title="重送置頂">📌</button>
              ) : (
                <button className="btn-pin" onClick={() => handlePinNote(data.noteId)}>📌</button>
              )
            )}
          </div>
        )}
        {canAdminDelete && (
          <div className="note-actions">
            <button className="btn-delete" onClick={() => handleDeleteNote(data.noteId, false, senderID)}>🗑️</button>
            <button className="btn-color" onClick={() => handleOpenColorPicker(data)}>🎨</button>
            {!isReply && !data.replyLoraMessageId && !data.isTempParentNote && data.status !== 'Sending' && !isTableCommand && (
              data.isPinedNote ? (
                <button className="btn-resend-pin" onClick={() => handleResendPin(data.noteId)} title="重送置頂">📌</button>
              ) : (
                <button className="btn-pin" onClick={() => handlePinNote(data.noteId)}>📌</button>
              )
            )}
          </div>
        )}
      </div>
    )
  }

  const renderNoteWithReplies = (note, index) => {
    const replyNotes = note.replyNotes || []
    const sortedReplies = [...replyNotes].sort((a, b) => {
      return new Date(a.timestamp || 0) - new Date(b.timestamp || 0)
    })
    
    // 找出整串便利貼中所有有 loraMessageId 的便利貼
    const allNotesWithLoraId = [note, ...sortedReplies].filter(n => n.loraMessageId)
    
    // 檢查是否正在回覆這串便利貼中的任何一張
    const isReplyingToThisThread = isReplyingTo && allNotesWithLoraId.some(n => n.loraMessageId === isReplyingTo)
    
    // 找出整串便利貼的最後一張（用於顯示 add-reply-btn）
    const lastNote = sortedReplies.length > 0 ? sortedReplies[sortedReplies.length - 1] : note
    const lastNoteLoraMessageId = lastNote.loraMessageId
    const lastNoteStatus = lastNote.status
    
    return (
      <div key={note.noteId || index} className="note-with-replies">
        {renderNote(note, index, false)}
        {sortedReplies.length > 0 && (
          <div className="reply-notes-container">
            {sortedReplies.map((reply, replyIdx) => renderNote(reply, `${index}-reply-${replyIdx}`, true))}
          </div>
        )}
        
        {isReplyingToThisThread ? (
          <div className="reply-notes-container">
            <div 
              className="sticky-note draft-note reply-note"
              style={{
                backgroundColor: COLOR_PALETTE[replyColorIndex],
                color: '#333'
              }}
            >
              <div className="draft-header">張貼回覆</div>
              <textarea
                ref={replyTextareaRef}
                className="draft-textarea"
                value={replyText}
                onChange={handleReplyTextChange}
                onCompositionStart={handleCompositionStart}
                onCompositionEnd={(e) => handleCompositionEnd(e, false)}
                placeholder="輸入回覆內容..."
                autoFocus
              />
              {mapEnabled && (
                <div className="draft-tools">
                  <button 
                    className="btn-location-picker"
                    onClick={handleOpenLocationPicker}
                    title="加入地圖座標"
                  >
                    📍 地圖座標
                  </button>
                </div>
              )}
              <div className="byte-counter-container">
                <div className="byte-counter-bar">
                  <div 
                    className="byte-counter-fill"
                    style={{ 
                      width: `${Math.min((replyByteCount / MAX_BYTES) * 100, 100)}%`,
                      backgroundColor: replyByteCount > MAX_BYTES ? '#d32f2f' : '#3498db'
                    }}
                  />
                </div>
                <div className="byte-counter-text" style={{ color: replyByteCount > MAX_BYTES ? '#d32f2f' : '#666' }}>
                  {replyByteCount}/{MAX_BYTES}
                </div>
              </div>
              <div className="color-picker">
                {COLOR_PALETTE.map((color, idx) => (
                  <div
                    key={idx}
                    className={`color-option ${replyColorIndex === idx ? 'selected' : ''}`}
                    style={{ backgroundColor: color }}
                    onClick={() => setReplyColorIndex(idx)}
                  />
                ))}
              </div>
              {!isAdmin && postPasscodeRequired && (
                <div className="passcode-input-container">
                  <input
                    type="password"
                    className="passcode-input"
                    placeholder="發送用通關碼"
                    value={replyPostPasscode}
                    onChange={(e) => setReplyPostPasscode(e.target.value)}
                  />
                </div>
              )}
              <div className="draft-actions">
                <button className="btn-cancel" onClick={handleCancelReply}>取消</button>
                <button className="btn-submit" onClick={handleSubmitReply} disabled={isSubmittingReply}>送出</button>
              </div>
            </div>
          </div>
        ) : (!isReplyingTo && lastNoteLoraMessageId && lastNoteStatus !== 'LAN only') ? (
          <div className="reply-notes-container">
            <button 
              className="add-reply-btn"
              onClick={() => handleCreateReply(lastNoteLoraMessageId)}
              disabled={isCreatingNote || isReplyingTo !== null}
            >
              +
            </button>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <>
      <header className={headerVisible ? 'header-visible' : 'header-hidden'}>
        <div className="header-left">
          <div
            className="board-name"
            onClick={() => { if (activeChannels.length > 1) setShowChannelDropdown(!showChannelDropdown) }}
            style={{ cursor: activeChannels.length > 1 ? 'pointer' : 'default' }}
          >
            {boardId}
            {channelVerifiedStatus[boardId] && channelVerifiedStatus[boardId].requiresPassword && (
              <span style={{ marginLeft: '4px' }}>
                {channelVerifiedStatus[boardId].isVerified ? '🔓' : '🔒'}
              </span>
            )}
            {activeChannels.length > 1 && (
              <span className="channel-arrow">{showChannelDropdown ? '▲' : '▼'}</span>
            )}
          </div>
          {showChannelDropdown && activeChannels.length > 1 && (
            <div className="channel-dropdown">
              {activeChannels.filter(ch => ch !== boardId).map(ch => (
                <div
                  key={ch}
                  className="channel-dropdown-item"
                  onClick={() => handleChannelSwitch(ch)}
                >
                  {ch}
                  {channelVerifiedStatus[ch] && channelVerifiedStatus[ch].requiresPassword && (
                    <span style={{ marginLeft: '4px' }}>
                      {channelVerifiedStatus[ch].isVerified ? '🔓' : '🔒'}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="app-label">{APP_SERVICE_NAME}</div>
        </div>
        
        <div className="status-container" style={{ position: 'relative' }}>
          <div className={`status-dot ${loraOnline ? (channelValidated ? 'online' : 'warning') : ''}`}></div>
          <div className="status-text">
            {loraOnline ? (channelValidated ? 'LoRa 連線' : 'LoRa 連線') : powerIssue ? 'LoRa 斷線 (RPi供電不足)' : 'LoRa 斷線'}
          </div>
          {loraOnline && !channelValidated && channelErrorMessage && (
            <div className="status-tooltip">
              {channelErrorMessage}
            </div>
          )}
        </div>
        <div className="user-role-container" onClick={handleUserRoleClick} style={{ cursor: 'pointer' }}>
          <div className="user-role-label">
            {isAdmin ? '👑頻道管理者' : '一般用戶'}
          </div>
        </div>
      </header>

      <div className={`noteboard-container ${viewMode === 'map' ? 'mapview-mode' : viewMode === 'table' ? 'tableview-mode' : ''}`}>
        {viewMode === 'sticky' && (
          <>
            <div className={`filter-bar ${isCreatingNote ? 'disabled' : ''}`}>
              <div className="filter-group">
                <label className="filter-label">排序：</label>
                <select 
                  className="filter-select"
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value)}
                  disabled={isCreatingNote}
                >
                  <option value="newest">日期時間由新到舊</option>
                  <option value="oldest">日期時間由舊到新</option>
                  <option value="color">顏色</option>
                </select>
              </div>

              <div className="filter-group">
                <label className="filter-label">關鍵字：</label>
                <input
                  ref={filterInputRef}
                  type="text"
                  className="filter-input"
                  placeholder=""
                  value={keywordFilter}
                  onChange={(e) => setKeywordFilter(e.target.value)}
                  disabled={isCreatingNote}
                  readOnly={filterInputReadonly}
                  onClick={() => {
                    if (filterInputReadonly) {
                      setFilterInputReadonly(false)
                      setTimeout(() => {
                        if (filterInputRef.current) {
                          filterInputRef.current.focus()
                        }
                      }, 0)
                    }
                  }}
                />
                {keywordFilter && (
                  <button 
                    className="clear-btn"
                    onClick={() => setKeywordFilter('')}
                    disabled={isCreatingNote}
                  >
                    ✕
                  </button>
                )}
              </div>

              <div className="filter-group">
                <button
                  className={`filter-advanced-toggle ${showAdvancedFilters ? 'active' : ''}`}
                  onClick={() => setShowAdvancedFilters(v => !v)}
                  disabled={isCreatingNote}
                  title="更多篩選"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                  </svg>
                </button>
              </div>

              {showAdvancedFilters && (
                <div className="filter-advanced-panel">
                  <label className="filter-checkbox">
                    <input
                      type="checkbox"
                      checked={showArchived}
                      onChange={(e) => setShowArchived(e.target.checked)}
                      disabled={isCreatingNote}
                    />
                    <span>顯示已封存</span>
                  </label>
                  <label className="filter-checkbox">
                    <input
                      type="checkbox"
                      checked={showTableCommands}
                      onChange={(e) => setShowTableCommands(e.target.checked)}
                      disabled={isCreatingNote}
                    />
                    <span>顯示表格指令</span>
                  </label>
                </div>
              )}
            </div>

            <div className="notes-grid">
              {getFilteredAndSortedNotes().map((note, idx) => renderNoteWithReplies(note, idx))}
              
              {isCreatingNote && (
                <div 
                  ref={draftNoteRef}
                  className="sticky-note draft-note"
                  style={{
                    backgroundColor: COLOR_PALETTE[draftColorIndex],
                    color: '#333'
                  }}
                >
                  <div className="draft-header">張貼便利貼</div>
                  <textarea
                    ref={draftTextareaRef}
                    className="draft-textarea"
                    value={draftText}
                    onChange={handleDraftTextChange}
                    onCompositionStart={handleCompositionStart}
                    onCompositionEnd={(e) => handleCompositionEnd(e, false)}
                    placeholder="輸入內容..."
                    autoFocus
                  />
                  {mapEnabled && (
                    <div className="draft-tools">
                      <button 
                        className="btn-location-picker"
                        onClick={handleOpenLocationPicker}
                        title="加入地圖座標"
                      >
                        📍 地圖座標
                      </button>
                    </div>
                  )}
                  <div className="byte-counter-container">
                    <div className="byte-counter-bar">
                      <div 
                        className="byte-counter-fill"
                        style={{ 
                          width: `${Math.min((draftByteCount / MAX_BYTES) * 100, 100)}%`,
                          backgroundColor: draftByteCount > MAX_BYTES ? '#d32f2f' : '#3498db'
                        }}
                      />
                    </div>
                    <div className="byte-counter-text" style={{ color: draftByteCount > MAX_BYTES ? '#d32f2f' : '#666' }}>
                      {draftByteCount}/{MAX_BYTES}
                    </div>
                  </div>
                  <div className="color-picker">
                    {COLOR_PALETTE.map((color, index) => (
                      <div
                        key={index}
                        className={`color-option ${draftColorIndex === index ? 'selected' : ''}`}
                        style={{ backgroundColor: color }}
                        onClick={() => setDraftColorIndex(index)}
                      />
                    ))}
                  </div>
                  {!isAdmin && postPasscodeRequired && (
                    <div className="passcode-input-container">
                      <input
                        type="password"
                        className="passcode-input"
                        placeholder="發送用通關碼"
                        value={draftPostPasscode}
                        onChange={(e) => setDraftPostPasscode(e.target.value)}
                      />
                    </div>
                  )}
                  <div className="draft-actions">
                    <button className="btn-cancel" onClick={handleCancelDraft}>取消</button>
                    <button className="btn-submit" onClick={handleSubmitDraft} disabled={isSubmittingDraft}>送出</button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <div style={{ display: viewMode === 'map' ? 'contents' : 'none' }}>
          <MapView
            notes={notes}
            boardId={boardId}
            isActive={viewMode === 'map'}
            onNavigateToNote={(noteId) => {
              setViewMode('sticky')
              // 切回 sticky view 後觸發地圖 slot 重新掃描
              setTimeout(() => {
                mapInstanceManager.triggerScan()
                const el = noteRefs.current[noteId]
                if (el) {
                  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  el.classList.add('note-highlight')
                  setTimeout(() => el.classList.remove('note-highlight'), 2000)
                }
              }, 150)
            }}
            onCreateNoteFromMap={(lat, lng) => {
              const coordStr = `@(${lat.toFixed(4)},${lng.toFixed(4)})`
              setViewMode('sticky')
              handleCreateNote(coordStr)
              // 切回 sticky view 後觸發地圖 slot 重新掃描
              setTimeout(() => mapInstanceManager.triggerScan(), 150)
            }}
          />
        </div>

        {viewMode === 'table' && (
          <TableView
            notes={notes}
            isActive={viewMode === 'table'}
            headerVisible={headerVisible}
            boardId={boardId}
            myUUID={myUUID}
            colorPalette={COLOR_PALETTE}
            isAdmin={isAdmin}
            postPasscodeRequired={postPasscodeRequired}
            loraOnline={loraOnline}
            sendIntervalSecond={SEND_INTERVAL_SECOND}
            globalLanOnlyCount={globalLanOnlyCount}
          />
        )}

      </div>

      {viewMode === 'sticky' && !isCreatingNote && !isReplyingTo && (
        <button className="fab" onClick={handleCreateNote}>
          +
        </button>
      )}

      <footer className="app-footer">
        <div className="footer-left">
          <div className="view-mode-tabs">
            <button
              className={`view-mode-tab ${viewMode === 'sticky' ? 'active' : ''}`}
              onClick={() => {
                if (isCreatingNote) handleCancelDraft()
                if (isReplyingTo) handleCancelReply()
                setViewMode('sticky')
                // 切回 sticky view 後觸發地圖 slot 重新掃描
                setTimeout(() => mapInstanceManager.triggerScan(), 150)
              }}
              title="便利貼模式"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <rect x="14" y="14" width="7" height="7" rx="1" />
              </svg>
            </button>
            {mapEnabled && (
            <button
              className={`view-mode-tab ${viewMode === 'map' ? 'active' : ''}`}
              onClick={() => {
                if (isCreatingNote) handleCancelDraft()
                if (isReplyingTo) handleCancelReply()
                setViewMode('map')
              }}
              title="地圖模式"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
                <circle cx="12" cy="9" r="2.5" />
              </svg>
            </button>
            )}
            <button
              className={`view-mode-tab ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => {
                if (isCreatingNote) handleCancelDraft()
                if (isReplyingTo) handleCancelReply()
                setViewMode('table')
              }}
              title="表格模式"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="1" />
                <line x1="3" y1="9" x2="21" y2="9" />
                <line x1="3" y1="15" x2="21" y2="15" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </svg>
            </button>
          </div>
        </div>
        <div className="footer-right">{APP_PROJECT_NAME} {APP_VERSION}</div>
      </footer>

      {modalConfig.show && (
        <div className="modal-overlay modal-overlay-top" onClick={() => modalConfig.type === 'alert' && modalConfig.onConfirm()}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">{modalConfig.title}</div>
            <div className="modal-body">{modalConfig.message}</div>
            <div className="modal-actions">
              {modalConfig.type === 'confirm' && (
                <button className="modal-btn modal-btn-cancel" onClick={modalConfig.onCancel}>
                  取消
                </button>
              )}
              <button className="modal-btn modal-btn-confirm" onClick={modalConfig.onConfirm}>
                {modalConfig.type === 'confirm' ? '確定' : '確定'}
              </button>
            </div>
          </div>
        </div>
      )}

      {colorPickerNote && (
        <div className="modal-overlay" onClick={handleCloseColorPicker}>
          <div className="modal-content color-picker-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">變更便利貼顏色</div>
            <div className="modal-body">
              <div className="color-picker">
                {COLOR_PALETTE.map((color, index) => (
                  <div
                    key={index}
                    className={`color-option ${selectedColorIndex === index ? 'selected' : ''}`}
                    style={{ backgroundColor: color }}
                    onClick={() => setSelectedColorIndex(index)}
                  />
                ))}
              </div>
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={handleCloseColorPicker}>
                取消
              </button>
              <button className="modal-btn modal-btn-confirm" onClick={handleSubmitColorChange}>
                確定
              </button>
            </div>
          </div>
        </div>
      )}

      {ackTooltip && ackData[ackTooltip] && (
        <div 
          className="ack-tooltip" 
          ref={ackTooltipRef}
          style={{
            top: `${ackTooltipPosition.top}px`,
            left: `${ackTooltipPosition.left}px`
          }}
        >
          <button 
            className="ack-tooltip-close"
            onClick={(e) => {
              e.stopPropagation()
              setAckTooltip(null)
            }}
          >
            ✕
          </button>
          <div className="ack-tooltip-header">已確認接收</div>
          <div className="ack-tooltip-list">
            {ackData[ackTooltip].map((ack, idx) => (
              <div key={ack.ackId || idx} className="ack-tooltip-item">
                {ack.displayId}
              </div>
            ))}
          </div>
        </div>
      )}

      {senderTooltip && senderTooltipData?.senderNodeDisplay && (
        <div 
          className="ack-tooltip" 
          ref={senderTooltipRef}
          style={{
            top: `${senderTooltipPosition.top}px`,
            left: `${senderTooltipPosition.left}px`
          }}
        >
          <button 
            className="ack-tooltip-close"
            onClick={(e) => {
              e.stopPropagation()
              setSenderTooltip(null)
              setSenderTooltipData(null)
            }}
          >
            ✕
          </button>
          <div className="ack-tooltip-header">發送節點</div>
          <div className="ack-tooltip-list">
            <div className="ack-tooltip-item">
              {senderTooltipData.senderNodeDisplay}
            </div>
          </div>
        </div>
      )}

      {showAdminModal && (
        <div className="modal-overlay" onClick={handleCloseAdminModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">管理者認證 - {boardId}</div>
            <div className="modal-body">
              <p>請輸入頻道 "{boardId}" 的管理者密碼：</p>
              <input
                type="password"
                className="admin-passcode-input"
                placeholder="輸入管理者密碼"
                value={adminPasscode}
                onChange={(e) => setAdminPasscode(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter') {
                    handleAdminAuthenticate()
                  }
                }}
                autoFocus
              />
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={handleCloseAdminModal}>
                取消
              </button>
              <button className="modal-btn modal-btn-confirm" onClick={handleAdminAuthenticate}>
                確定
              </button>
            </div>
          </div>
        </div>
      )}

      {showPasswordModal && (
        <div className="modal-overlay" onClick={handlePasswordCancel}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">頻道密碼驗證</div>
            <div className="modal-body">
              <p>頻道 "{pendingChannel}" 需要密碼才能進入：</p>
              <input
                type="password"
                className="admin-passcode-input"
                placeholder="輸入頻道密碼"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter') {
                    handlePasswordSubmit()
                  }
                }}
                autoFocus
              />
              {passwordError && (
                <p style={{ color: '#e74c3c', marginTop: '8px', fontSize: '0.9em' }}>{passwordError}</p>
              )}
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={handlePasswordCancel}>
                取消
              </button>
              <button className="modal-btn modal-btn-confirm" onClick={handlePasswordSubmit}>
                確定
              </button>
            </div>
          </div>
        </div>
      )}

      {showLocationPicker && (
        <LocationPicker
          onConfirm={handleLocationConfirm}
          onCancel={handleCloseLocationPicker}
          initialText={editingNoteId ? editText : (isReplyingTo ? replyText : draftText)}
          lastLocation={myUUID ? userLastLocations[myUUID] : null}
        />
      )}
    </>
  )
}

export default App
