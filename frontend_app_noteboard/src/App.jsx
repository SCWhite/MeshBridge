import { useState, useEffect, useRef } from 'react'
import { io } from 'socket.io-client'

const BOARD_ID = 'WangsFamily'

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
  'hsl(15, 80%, 85%)'      // 15: Coral
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
  const [nickname, setNickname] = useState('')
  const [noteInput, setNoteInput] = useState('')
  const [loraOnline, setLoraOnline] = useState(false)
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

  const fetchNotes = async (includeDeleted = false) => {
    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes?is_include_deleted=${includeDeleted}`)
      const data = await response.json()
      if (data.success) {
        setNotes(data.notes)
      }
    } catch (error) {
      console.error('Failed to fetch notes:', error)
    }
  }

  useEffect(() => {
    const initializeApp = async () => {
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

      const savedNick = localStorage.getItem('mesh_nickname')
      if (savedNick) {
        setNickname(savedNick)
      }

      fetchNotes(showArchived)

      const newSocket = io()
      setSocket(newSocket)

      newSocket.on('lora_status', (data) => {
        setLoraOnline(data.online)
      })

      newSocket.on('refresh_notes', (data) => {
        if (data.board_id === BOARD_ID) {
          fetchNotes(showArchived)
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

  useEffect(() => {
    fetchNotes(showArchived)
  }, [showArchived])

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
        }
      }, 150)
    }
  }, [isCreatingNote])


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

  const handleNicknameChange = (e) => {
    const value = e.target.value
    setNickname(value)
    localStorage.setItem('mesh_nickname', value)
  }

  const addNote = () => {
    const text = noteInput.trim()
    const nick = nickname.trim()
    
    if (!nick) {
      showAlert("請先輸入暱稱！")
      return
    }
    if (!text) return

    socket.emit('send_mesh', {
      text: text,
      sender: nick,
      userId: myUUID
    })
    
    setNoteInput('')
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      addNote()
    }
  }

  const deleteNote = async (index) => {
    const newNotes = notes.filter((_, i) => i !== index)
    setNotes(newNotes)
  }

  const handleCreateNote = () => {
    setIsCreatingNote(true)
    setDraftText('')
    setDraftColorIndex(0)
    setDraftByteCount(0)
  }

  const handleCancelDraft = () => {
    setIsCreatingNote(false)
    setDraftText('')
    setDraftColorIndex(0)
    setDraftByteCount(0)
  }

  const handleCreateReply = (parentNoteId) => {
    setIsReplyingTo(parentNoteId)
    setReplyText('')
    setReplyColorIndex(0)
    setReplyByteCount(0)
  }

  const handleCancelReply = () => {
    setIsReplyingTo(null)
    setReplyText('')
    setReplyColorIndex(0)
    setReplyByteCount(0)
  }

  const handleSubmitReply = async () => {
    const text = replyText.trim()
    if (!text) {
      showAlert('請輸入回覆內容！')
      return
    }

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: text,
          author_key: myUUID,
          color_index: replyColorIndex,
          parent_note_id: isReplyingTo
        })
      })

      const data = await response.json()
      if (data.success) {
        setIsReplyingTo(null)
        setReplyText('')
        setReplyColorIndex(0)
        setReplyByteCount(0)
      } else {
        showAlert('張貼回覆失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to create reply:', error)
      showAlert('張貼回覆失敗：' + error.message, '錯誤')
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

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          text: text,
          author_key: myUUID,
          color_index: draftColorIndex
        })
      })

      const data = await response.json()
      if (data.success) {
        setIsCreatingNote(false)
        setDraftText('')
        setDraftColorIndex(0)
        setDraftByteCount(0)
      } else {
        showAlert('建立便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to create note:', error)
      showAlert('建立便利貼失敗：' + error.message, '錯誤')
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

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes/${noteId}`, {
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
    }
  }

  const handleDeleteNote = async (noteId) => {
    const confirmed = await showConfirm('確定要刪除這個便利貼嗎？', '刪除確認')
    if (!confirmed) {
      return
    }

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes/${noteId}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          author_key: myUUID
        })
      })

      const data = await response.json()
      if (!data.success) {
        showAlert('刪除便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
      showAlert('刪除便利貼失敗：' + error.message, '錯誤')
    }
  }

  const handleArchiveNote = async (noteId) => {
    const confirmed = await showConfirm('確定要封存這個便利貼嗎？封存後將從佈告欄移除。', '封存確認')
    if (!confirmed) {
      return
    }

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes/${noteId}/archive`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          author_key: myUUID
        })
      })

      const data = await response.json()
      if (!data.success) {
        showAlert('封存便利貼失敗：' + (data.error || '未知錯誤'), '錯誤')
      }
    } catch (error) {
      console.error('Failed to archive note:', error)
      showAlert('封存便利貼失敗：' + error.message, '錯誤')
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

    try {
      const response = await fetch(`/api/boards/${BOARD_ID}/notes/${colorPickerNote.noteId}/color`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          author_key: myUUID,
          color_index: selectedColorIndex
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
        return 'LoRa發送'
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
    const canEdit = isMyNote && status === 'LAN only'
    const canManage = isMyNote && status !== 'LAN only'
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
            <button className="btn-submit" onClick={() => handleSubmitEdit(data.noteId)}>更新</button>
            <button className="btn-cancel" onClick={handleCancelEdit}>取消</button>
          </div>
        </div>
      )
    }

    return (
      <div 
        key={data.noteId || index} 
        className={`sticky-note ${status === 'local' ? 'note-failed' : ''} ${isReordering ? 'reordering' : ''} ${isReply ? 'reply-note' : ''}`}
        style={{
          backgroundColor: bgColor,
          color: '#333'
        }}
      >
        <div className="note-content">{highlightText(text, keywordFilter)}</div>
        <div className="note-footer">
          <span className="note-time">{time}</span>
          <span className="note-status">{getStatusDisplay(status)}</span>
        </div>
        {canEdit && (
          <div className="note-actions">
            <button className="btn-edit" onClick={() => handleEditNote(data)}>✏️</button>
            <button className="btn-delete" onClick={() => handleDeleteNote(data.noteId)}>🗑️</button>
          </div>
        )}
        {canManage && (
          <div className="note-actions">
            <button className="btn-archive" onClick={() => handleArchiveNote(data.noteId)}>📦</button>
            <button className="btn-color" onClick={() => handleOpenColorPicker(data)}>🎨</button>
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
    
    // 找出整串便利貼的最後一張（用於回覆）
    const lastNote = sortedReplies.length > 0 ? sortedReplies[sortedReplies.length - 1] : note
    const lastNoteLoraMessageId = lastNote.loraMessageId
    const lastNoteStatus = lastNote.status
    
    const isReplyingToThis = isReplyingTo === lastNoteLoraMessageId && lastNoteLoraMessageId && lastNoteStatus !== 'LAN only'
    
    return (
      <div key={note.noteId || index} className="note-with-replies">
        {renderNote(note, index, false)}
        {sortedReplies.length > 0 && (
          <div className="reply-notes-container">
            {sortedReplies.map((reply, replyIdx) => renderNote(reply, `${index}-reply-${replyIdx}`, true))}
          </div>
        )}
        
        {isReplyingToThis ? (
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
              <div className="draft-actions">
                <button className="btn-submit" onClick={handleSubmitReply}>送出</button>
                <button className="btn-cancel" onClick={handleCancelReply}>取消</button>
              </div>
            </div>
          </div>
        ) : (lastNoteLoraMessageId && lastNoteStatus !== 'LAN only') ? (
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
          <div className="app-name">MeshBridge: {BOARD_ID} 便利貼公告欄</div>
          <div className="app-link">noteboard.meshbridge.com</div>
        </div>
        
        <div className="status-container">
          <div className={`status-dot ${loraOnline ? 'online' : ''}`}></div>
          <div className="status-text">
            {loraOnline ? 'LoRa 連線' : 'LoRa 斷線'}
          </div>
        </div>
      </header>

      <div className="noteboard-container">
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
              type="text"
              className="filter-input"
              placeholder=""
              value={keywordFilter}
              onChange={(e) => setKeywordFilter(e.target.value)}
              disabled={isCreatingNote}
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
            <label className="filter-checkbox">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
                disabled={isCreatingNote}
              />
              <span>顯示已封存</span>
            </label>
          </div>
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
              <div className="draft-actions">
                <button className="btn-submit" onClick={handleSubmitDraft}>送出</button>
                <button className="btn-cancel" onClick={handleCancelDraft}>取消</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {!isCreatingNote && (
        <button className="fab" onClick={handleCreateNote}>
          +
        </button>
      )}

      <footer className="app-footer">
        <div className="footer-left">uid={myUUID}</div>
        <div className="footer-right">mqBoard v0.1.0</div>
      </footer>

      {modalConfig.show && (
        <div className="modal-overlay" onClick={() => modalConfig.type === 'alert' && modalConfig.onConfirm()}>
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
    </>
  )
}

export default App
