import { useState, useEffect, useRef, useMemo, useCallback } from 'react'

// {sheetId:cellId}content
// sheetId: 6 chars [a-z0-9], cellId: [A-Z][1-999] or "title"
export const TABLE_CELL_RE = /^\{([a-z0-9]{6}):((?:[A-Z][1-9]\d{0,2})|title)\}([\s\S]*)$/
const SHEET_DELETE_RE = /^\{([a-z0-9]{6}):delete\}$/

const DEFAULT_COLOR_INDEX = 15

const isWhiteColor = (color) => {
  if (!color) return true
  const c = color.trim().toLowerCase()
  return c === 'white' || c === '#fff' || c === '#ffffff' ||
    c === 'rgb(255, 255, 255)' || c === 'rgb(255,255,255)' ||
    c === 'hsl(0, 0%, 100%)' || c === 'hsl(0,0%,100%)'
}

// Utility function to check if notes contain table data
export function hasTableData(notes) {
  if (!notes || notes.length === 0) return false
  return notes.some(note => {
    if (note.archived) return false
    const body = (note.text || '').trim()
    return TABLE_CELL_RE.test(body)
  })
}

function parseSheets(notes, baseTableData) {
  const sheets = {}
  // 收集所有已刪除的 sheetId，一旦刪除永久排除
  const deletedSheets = new Set()

  // 1. Apply base table data (pre-max_notes history) as foundation
  if (baseTableData) {
    // 先載入後端已偵測到的已刪除 sheetId
    if (baseTableData.deleted_sheets) {
      baseTableData.deleted_sheets.forEach(sid => deletedSheets.add(sid))
    }
    if (baseTableData.titles) {
      for (const [sheetId, title] of Object.entries(baseTableData.titles)) {
        if (deletedSheets.has(sheetId)) continue
        if (!sheets[sheetId]) sheets[sheetId] = { title: '', cells: {} }
        sheets[sheetId].title = title
      }
    }
    if (baseTableData.cells) {
      for (const cell of baseTableData.cells) {
        const sheetId = cell.s
        if (deletedSheets.has(sheetId)) continue
        if (!sheets[sheetId]) sheets[sheetId] = { title: '', cells: {} }
        const cellId = String.fromCharCode(65 + cell.c) + cell.r
        sheets[sheetId].cells[cellId] = { content: cell.t, bgColor: cell.bg || '' }
      }
    }
  }

  // 2. Overlay current notes (newest max_notes), newer overwrites older
  const sorted = [...(notes || [])].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
  sorted.forEach(note => {
    if (note.archived) return
    const body = (note.text || '').trim()

    // 偵測工作表刪除指令，永久排除該 sheetId
    const dm = body.match(SHEET_DELETE_RE)
    if (dm) {
      const sid = dm[1]
      deletedSheets.add(sid)
      delete sheets[sid]
      return
    }

    const m = body.match(TABLE_CELL_RE)
    if (!m) return
    const sheetId = m[1]
    const cellId = m[2]
    const content = m[3]
    // 已刪除的 sheetId 永久排除，不再接受任何資料
    if (deletedSheets.has(sheetId)) return
    if (!sheets[sheetId]) sheets[sheetId] = { title: '', cells: {} }
    if (cellId === 'title') {
      sheets[sheetId].title = content.trim()
    } else {
      sheets[sheetId].cells[cellId] = { content, bgColor: note.bgColor || '' }
    }
  })
  return sheets
}

function TableView({ notes, isActive, onAddRow, headerVisible = true, boardId, myUUID, colorPalette = [], isAdmin = false, postPasscodeRequired = false, loraOnline = false, sendIntervalSecond = 30, globalLanOnlyCount = 0 }) {
  const [activeSheetId, setActiveSheetId] = useState(null)
  const [extraRows, setExtraRows] = useState(0)
  const [extraCols, setExtraCols] = useState(0)
  const [baseTableData, setBaseTableData] = useState(null)
  const tabsRef = useRef(null)

  // Editing state
  const [editingCell, setEditingCell] = useState(null) // { sheetId, cellId }
  const [editText, setEditText] = useState('')
  const [editColorIndex, setEditColorIndex] = useState(DEFAULT_COLOR_INDEX)
  const [originalText, setOriginalText] = useState('')
  const [originalColorIndex, setOriginalColorIndex] = useState(DEFAULT_COLOR_INDEX)
  const [showColorPicker, setShowColorPicker] = useState(false)
  const [colorPickerBelow, setColorPickerBelow] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const editCellRef = useRef(null)
  const toolbarRef = useRef(null)

  // Highlight state: one row or one column at a time
  const [highlight, setHighlight] = useState(null)

  // Sheet name modal state
  const [showSheetModal, setShowSheetModal] = useState(false)
  const [sheetModalMode, setSheetModalMode] = useState('create') // 'create' | 'rename'
  const [sheetModalName, setSheetModalName] = useState('')
  const [sheetModalTargetId, setSheetModalTargetId] = useState(null)
  const [isSubmittingSheet, setIsSubmittingSheet] = useState(false)

  // Delete sheet modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteTargetSheetId, setDeleteTargetSheetId] = useState(null)
  const [isDeletingSheet, setIsDeletingSheet] = useState(false)

  // Post passcode modal state
  const [showPasscodeModal, setShowPasscodeModal] = useState(false)
  const [passcodeInput, setPasscodeInput] = useState('')
  const [passcodeError, setPasscodeError] = useState('')
  const [pendingSubmitType, setPendingSubmitType] = useState(null) // 'cell' | 'sheet'

  // Count LAN-only table-cell notes for send countdown
  const lanOnlyTableCount = useMemo(() => {
    if (!notes || notes.length === 0) return 0
    return notes.filter(note => {
      if (note.archived) return false
      const body = (note.text || '').trim()
      if (!TABLE_CELL_RE.test(body)) return false
      return note.status === 'LAN only'
    }).length
  }, [notes])

  // Send completion countdown timer
  const [countdown, setCountdown] = useState(0)
  const countdownRef = useRef(0)

  useEffect(() => {
    const total = globalLanOnlyCount * sendIntervalSecond
    setCountdown(total)
    countdownRef.current = total
  }, [globalLanOnlyCount, sendIntervalSecond])

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setInterval(() => {
      setCountdown(prev => {
        const next = prev - 1
        countdownRef.current = next
        return next <= 0 ? 0 : next
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [countdown > 0])

  const showCountdown = loraOnline && lanOnlyTableCount > 0 && countdown > 0

  const formatCountdown = (secs) => {
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    const s = secs % 60
    if (h > 0) {
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  // Fetch base table data (pre-max_notes history) when boardId changes
  useEffect(() => {
    if (!boardId) return
    let cancelled = false
    const fetchBase = async () => {
      try {
        const response = await fetch(`/api/boards/${boardId}/table-base`)
        const data = await response.json()
        if (!cancelled && data.success) {
          setBaseTableData(data)
        }
      } catch (error) {
        console.error('Failed to fetch table base data:', error)
      }
    }
    fetchBase()
    return () => { cancelled = true }
  }, [boardId])

  const sheets = useMemo(() => parseSheets(notes, baseTableData), [notes, baseTableData])
  const sheetIds = useMemo(() => Object.keys(sheets), [sheets])

  // keep activeSheetId valid; restore from localStorage per board
  useEffect(() => {
    setActiveSheetId(prev => {
      try {
        const remembered = localStorage.getItem(`tableview_lastSheet_${boardId}`)
        if (remembered && sheetIds.includes(remembered)) return remembered
      } catch {}
      if (prev && sheetIds.includes(prev)) return prev
      return sheetIds.length > 0 ? sheetIds[0] : null
    })
  }, [sheetIds, boardId])

  // persist activeSheetId to localStorage per board
  useEffect(() => {
    if (activeSheetId && boardId && sheetIds.includes(activeSheetId)) {
      try { localStorage.setItem(`tableview_lastSheet_${boardId}`, activeSheetId) } catch {}
    }
  }, [activeSheetId, boardId, sheetIds])

  // Clear highlight and cancel editing on worksheet or channel switch
  useEffect(() => { setHighlight(null); cancelEditing() }, [activeSheetId, boardId])

  // scroll active tab into view
  useEffect(() => {
    if (tabsRef.current) {
      const activeBtn = tabsRef.current.querySelector('.tv-tab.is-active')
      if (activeBtn) {
        activeBtn.scrollIntoView({ inline: 'center', block: 'nearest' })
      }
    }
  }, [activeSheetId])

  // Close color picker when clicking outside
  useEffect(() => {
    if (!showColorPicker) return
    const handleClickOutside = (e) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target)) {
        setShowColorPicker(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showColorPicker])

  // Generate a random 6-char lowercase alphanumeric sheetId
  const generateSheetId = () => {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    const bytes = crypto.getRandomValues(new Uint8Array(6))
    let id = ''
    for (let i = 0; i < 6; i++) id += chars[bytes[i] % 36]
    return id
  }

  const openCreateSheetModal = useCallback(() => {
    setSheetModalMode('create')
    setSheetModalName('新工作表')
    setSheetModalTargetId(null)
    setShowSheetModal(true)
  }, [])

  const openDeleteSheetModal = useCallback((sid) => {
    setDeleteTargetSheetId(sid)
    setShowDeleteModal(true)
  }, [])

  const closeDeleteSheetModal = useCallback(() => {
    setShowDeleteModal(false)
    setDeleteTargetSheetId(null)
  }, [])

  const confirmDeleteSheet = useCallback(async () => {
    const sid = deleteTargetSheetId
    if (!boardId || !sid || isDeletingSheet) return

    const noteBody = `{${sid}:delete}`
    setIsDeletingSheet(true)
    try {
      const response = await fetch(`/api/boards/${boardId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: noteBody,
          author_key: myUUID,
          color_index: DEFAULT_COLOR_INDEX,
          post_passcode: ''
        })
      })
      const data = await response.json()
      if (data.success) {
        if (activeSheetId === sid) {
          const remaining = sheetIds.filter(id => id !== sid)
          setActiveSheetId(remaining.length > 0 ? remaining[0] : null)
        }
      } else {
        console.error('Failed to delete sheet:', data.error)
      }
    } catch (error) {
      console.error('Failed to delete sheet:', error)
    } finally {
      setIsDeletingSheet(false)
      setShowDeleteModal(false)
      setDeleteTargetSheetId(null)
    }
  }, [boardId, myUUID, isDeletingSheet, deleteTargetSheetId, activeSheetId, sheetIds])

  const openRenameSheetModal = useCallback((sid) => {
    setSheetModalMode('rename')
    setSheetModalName(getSheetTitle(sid))
    setSheetModalTargetId(sid)
    setShowSheetModal(true)
  }, [sheets])

  const closeSheetModal = useCallback(() => {
    setShowSheetModal(false)
    setSheetModalName('')
    setSheetModalTargetId(null)
  }, [])

  const submitSheetWithPasscode = useCallback(async (passcode = '') => {
    if (!boardId || isSubmittingSheet) return
    const trimmed = sheetModalName.trim()
    if (!trimmed) return

    const sid = sheetModalMode === 'create' ? generateSheetId() : sheetModalTargetId
    const noteBody = `{${sid}:title}${trimmed}`

    setIsSubmittingSheet(true)
    try {
      const payload = {
        text: noteBody,
        author_key: myUUID,
        color_index: DEFAULT_COLOR_INDEX,
        post_passcode: passcode
      }
      if (sheetModalMode === 'create') payload.is_new_sheet = true
      const response = await fetch(`/api/boards/${boardId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      const data = await response.json()
      if (data.success) {
        closeSheetModal()
        setShowPasscodeModal(false)
        setPasscodeInput('')
        setPasscodeError('')
        setPendingSubmitType(null)
        if (sheetModalMode === 'create') {
          setActiveSheetId(data.sheet_id || sid)
        }
      } else {
        if (passcode) {
          setPasscodeError(data.error || '通關碼錯誤')
        } else {
          console.error('Failed to post sheet title note:', data.error)
        }
      }
    } catch (error) {
      console.error('Failed to post sheet title note:', error)
    } finally {
      setIsSubmittingSheet(false)
    }
  }, [boardId, myUUID, sheetModalMode, sheetModalName, sheetModalTargetId, isSubmittingSheet, closeSheetModal])

  const confirmSheetModal = useCallback(() => {
    if (!boardId || isSubmittingSheet) return
    const trimmed = sheetModalName.trim()
    if (!trimmed) return

    // Admin bypasses passcode; non-admin with postPasscodeRequired shows passcode modal
    if (!isAdmin && postPasscodeRequired) {
      setPendingSubmitType('sheet')
      setPasscodeInput('')
      setPasscodeError('')
      setShowPasscodeModal(true)
      return
    }

    submitSheetWithPasscode('')
  }, [boardId, isSubmittingSheet, sheetModalName, isAdmin, postPasscodeRequired, submitSheetWithPasscode])

  const getSheetTitle = (id) => {
    const s = sheets[id]
    return (s && s.title) ? s.title : id
  }

  const startEditing = useCallback((sheetId, cellId, currentContent, cellBgColor) => {
    if (editingCell) return // already editing
    let initIdx = DEFAULT_COLOR_INDEX
    if (cellBgColor && colorPalette.length > 0) {
      const found = colorPalette.findIndex(c => c.toLowerCase() === cellBgColor.toLowerCase())
      if (found !== -1) initIdx = found
    }
    setEditingCell({ sheetId, cellId })
    setEditText(currentContent)
    setOriginalText(currentContent)
    setEditColorIndex(initIdx)
    setOriginalColorIndex(initIdx)
    setShowColorPicker(false)
  }, [editingCell, colorPalette])

  const cancelEditing = useCallback(() => {
    setEditingCell(null)
    setEditText('')
    setOriginalText('')
    setEditColorIndex(DEFAULT_COLOR_INDEX)
    setOriginalColorIndex(DEFAULT_COLOR_INDEX)
    setShowColorPicker(false)
  }, [])

  const submitCellWithPasscode = useCallback(async (passcode = '') => {
    if (!editingCell || !boardId || isSubmitting) return

    const trimmed = editText.trim()
    const noteBody = `{${editingCell.sheetId}:${editingCell.cellId}}${trimmed}`

    setIsSubmitting(true)
    try {
      const response = await fetch(`/api/boards/${boardId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: noteBody,
          author_key: myUUID,
          color_index: editColorIndex,
          post_passcode: passcode
        })
      })
      const data = await response.json()
      if (data.success) {
        cancelEditing()
        setShowPasscodeModal(false)
        setPasscodeInput('')
        setPasscodeError('')
        setPendingSubmitType(null)
      } else {
        if (passcode) {
          setPasscodeError(data.error || '通關碼錯誤')
        } else {
          console.error('Failed to post table cell note:', data.error)
        }
      }
    } catch (error) {
      console.error('Failed to post table cell note:', error)
    } finally {
      setIsSubmitting(false)
    }
  }, [editingCell, editText, editColorIndex, boardId, myUUID, isSubmitting, cancelEditing])

  const confirmEditing = useCallback(() => {
    if (!editingCell || !boardId || isSubmitting) return

    const trimmed = editText.trim()
    // No change -> just exit edit mode
    if (trimmed === originalText.trim() && editColorIndex === originalColorIndex) {
      cancelEditing()
      return
    }

    // Admin bypasses passcode; non-admin with postPasscodeRequired shows passcode modal
    if (!isAdmin && postPasscodeRequired) {
      setPendingSubmitType('cell')
      setPasscodeInput('')
      setPasscodeError('')
      setShowPasscodeModal(true)
      return
    }

    submitCellWithPasscode('')
  }, [editingCell, editText, originalText, editColorIndex, originalColorIndex, boardId, isSubmitting, cancelEditing, isAdmin, postPasscodeRequired, submitCellWithPasscode])

  const handlePasscodeConfirm = useCallback(() => {
    const code = passcodeInput.trim()
    if (!code) {
      setPasscodeError('請輸入資料輸入密碼')
      return
    }
    if (pendingSubmitType === 'cell') {
      submitCellWithPasscode(code)
    } else if (pendingSubmitType === 'sheet') {
      submitSheetWithPasscode(code)
    }
  }, [passcodeInput, pendingSubmitType, submitCellWithPasscode, submitSheetWithPasscode])

  const handlePasscodeCancel = useCallback(() => {
    setShowPasscodeModal(false)
    setPasscodeInput('')
    setPasscodeError('')
    setPendingSubmitType(null)
  }, [])

  if (sheetIds.length === 0) {
    return (
      <div className="tv-empty">
        <svg className="tv-empty-icon" width="56" height="56" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="6" y="10" width="44" height="36" rx="4" stroke="#bdc1c6" strokeWidth="2.2" />
          <line x1="6" y1="20" x2="50" y2="20" stroke="#bdc1c6" strokeWidth="2.2" />
          <line x1="6" y1="30" x2="50" y2="30" stroke="#dadce0" strokeWidth="1.5" />
          <line x1="6" y1="38" x2="50" y2="38" stroke="#dadce0" strokeWidth="1.5" />
          <line x1="20" y1="20" x2="20" y2="46" stroke="#dadce0" strokeWidth="1.5" />
          <line x1="36" y1="20" x2="36" y2="46" stroke="#dadce0" strokeWidth="1.5" />
        </svg>
        <div className="tv-empty-msg">暫無表格資料，可等待接收其他節點資料，或以管理者身份建立新工作表..</div>
        {isAdmin && (
          <button className="tv-empty-btn" onClick={openCreateSheetModal}>建立新工作表</button>
        )}
        {showSheetModal && (
          <div className="modal-overlay" onClick={closeSheetModal}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">{sheetModalMode === 'create' ? '新建立工作表' : '工作表名稱異動'}</div>
              <div className="modal-body">
                <label className="tv-sheet-modal-label">工作表名稱</label>
                <input
                  type="text"
                  className="admin-passcode-input tv-sheet-name-input"
                  value={sheetModalName}
                  onChange={(e) => setSheetModalName(e.target.value)}
                  maxLength={50}
                  onKeyDown={(e) => { if (e.key === 'Enter') confirmSheetModal() }}
                  autoFocus
                />
              </div>
              <div className="modal-actions">
                <button className="modal-btn modal-btn-cancel" onClick={closeSheetModal}>取消</button>
                <button className="modal-btn modal-btn-confirm" onClick={confirmSheetModal} disabled={isSubmittingSheet || !sheetModalName.trim()}>確定</button>
              </div>
            </div>
          </div>
        )}
        {showDeleteModal && deleteTargetSheetId && (
          <div className="modal-overlay" onClick={closeDeleteSheetModal}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">刪除工作表</div>
              <div className="modal-body">
                <p>確認要刪除工作表「{getSheetTitle(deleteTargetSheetId)}」？刪除後無法復原，並會同步影響其他節點中的內容。</p>
              </div>
              <div className="modal-actions">
                <button className="modal-btn modal-btn-cancel" onClick={closeDeleteSheetModal}>取消</button>
                <button className="modal-btn modal-btn-confirm" onClick={confirmDeleteSheet} disabled={isDeletingSheet} style={{ background: '#d32f2f' }}>刪除</button>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  const sheet = activeSheetId ? sheets[activeSheetId] : null
  const cells = (sheet && sheet.cells) || {}
  const cellKeys = Object.keys(cells)

  // compute grid bounds
  let maxColIdx = 0
  let maxRow = 0
  cellKeys.forEach(key => {
    const col = key.charCodeAt(0) - 65
    const row = parseInt(key.substring(1), 10)
    if (col > maxColIdx) maxColIdx = col
    if (row > maxRow) maxRow = row
  })
  // Auto-pad to 10 columns minimum, then add extraCols
  const baseCols = Math.max(cellKeys.length > 0 ? maxColIdx + 1 : 0, 10)
  const numCols = baseCols + extraCols
  // 3 extra blank columns for [+] button area
  const totalCols = numCols + 3
  // Auto-pad to 20 rows minimum
  const baseRows = Math.max(maxRow, 20)
  const numRows = baseRows + extraRows

  // Column widths: row header 80px, data columns 90-160px
  const rowHeaderWidth = 40
  const minColW = 90
  const maxColW = 160

  const truncate = (str, max) => {
    if (!str) return ''
    return str.length > max ? str.substring(0, max) + '…' : str
  }

  const handleAddRow = () => {
    setExtraRows(prev => prev + 1)
  }

  const handleAddCol = () => {
    setExtraCols(prev => prev + 1)
  }

  const isEditingCell = (sheetId, cellId) => {
    return editingCell && editingCell.sheetId === sheetId && editingCell.cellId === cellId
  }

  const renderCell = (cellId, c, rowNum) => {
    const cell = cells[cellId]
    const val = cell ? cell.content : ''
    const bgStyle = cell && cell.bgColor
      ? { width: 120, minWidth: 120, backgroundColor: cell.bgColor }
      : { width: 120, minWidth: 120 }

    const editing = isEditingCell(activeSheetId, cellId)
    const isHighlighted = !editing && highlight && (
      (highlight.type === 'row' && rowNum === highlight.index) ||
      (highlight.type === 'col' && c === highlight.index)
    )
    const hasBgColor = cell && cell.bgColor && !isWhiteColor(cell.bgColor)

    if (editing) {
      return (
        <td
          key={c}
          className="tv-cell tv-cell-editing"
          style={{ ...bgStyle, position: 'relative', overflow: 'visible' }}
          ref={editCellRef}
        >
          <textarea
            className="tv-cell-input"
            style={colorPalette[editColorIndex] ? { backgroundColor: colorPalette[editColorIndex] } : undefined}
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                cancelEditing()
              }
            }}
          />
          <div className="tv-cell-toolbar" ref={toolbarRef}>
            <button
              className="tv-toolbar-btn tv-toolbar-confirm"
              onClick={confirmEditing}
              disabled={isSubmitting}
              title="確認"
            >
              ✓
            </button>
            <button
              className="tv-toolbar-btn tv-toolbar-cancel"
              onClick={cancelEditing}
              title="取消"
            >
              ✕
            </button>
            <div className="tv-toolbar-color-wrapper">
              <button
                className="tv-toolbar-btn tv-toolbar-color"
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect()
                  setColorPickerBelow(rect.top < 200)
                  setShowColorPicker(!showColorPicker)
                }}
                title="變更顏色"
              >
                🎨
              </button>
              {showColorPicker && colorPalette.length > 0 && (
                <div className={`tv-color-dropdown${colorPickerBelow ? ' drop-down' : ''}`}>
                  {colorPalette.map((color, idx) => (
                    <div
                      key={idx}
                      className={`tv-color-option ${editColorIndex === idx ? 'selected' : ''}`}
                      style={{ backgroundColor: color }}
                      onClick={() => {
                        setEditColorIndex(idx)
                        setShowColorPicker(false)
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </td>
      )
    }

    return (
      <td
        key={c}
        className={`tv-cell${isHighlighted ? ' tv-cell-hl' : ''}${isHighlighted && !hasBgColor ? ' tv-cell-hl-nobg' : ''}`}
        title={val}
        style={bgStyle}
        onClick={() => startEditing(activeSheetId, cellId, val, cell ? cell.bgColor : '')}
      >
        {val}
      </td>
    )
  }

  return (
    <div className={`tv-wrapper ${headerVisible ? 'header-visible' : 'header-hidden'}`}>
      <div className="tv-grid-area">
        <table className="tv-grid" style={{ '--row-header-width': `${rowHeaderWidth}px` }}>
          <colgroup>
            <col style={{ width: rowHeaderWidth }} />
            {Array.from({ length: totalCols }, (_, i) => (
              <col key={i} style={{ width: '120px' }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="tv-corner" style={{ width: rowHeaderWidth, minWidth: rowHeaderWidth, maxWidth: rowHeaderWidth }}></th>
              {Array.from({ length: numCols }, (_, c) => (
                <th
                  key={c}
                  style={{ width: 120, minWidth: 120 }}
                  className={highlight && highlight.type === 'col' && highlight.index === c ? 'tv-hl-active' : ''}
                  onClick={() => setHighlight(prev => prev && prev.type === 'col' && prev.index === c ? null : { type: 'col', index: c })}
                >{String.fromCharCode(65 + c)}</th>
              ))}
              {/* 3 blank column headers with [+] in first */}
              {Array.from({ length: 3 }, (_, i) => (
                <th key={`blank-col-${i}`} className="tv-blank-col-header" style={{ width: 120, minWidth: 120 }}>
                  {i === 0 ? (
                    <button className="tv-add-col-btn" onClick={handleAddCol} title="新增一欄">+</button>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: numRows }, (_, r) => {
              const rowNum = r + 1
              return (
                <tr key={rowNum}>
                  <th
                    className={`tv-row-header${highlight && highlight.type === 'row' && highlight.index === rowNum ? ' tv-hl-active' : ''}`}
                    style={{ width: rowHeaderWidth, minWidth: rowHeaderWidth, maxWidth: rowHeaderWidth }}
                    onClick={() => setHighlight(prev => prev && prev.type === 'row' && prev.index === rowNum ? null : { type: 'row', index: rowNum })}
                  >{rowNum}</th>
                  {Array.from({ length: numCols }, (_, c) => {
                    const cellId = String.fromCharCode(65 + c) + rowNum
                    return renderCell(cellId, c, rowNum)
                  })}
                  {/* 3 blank cells for extra columns */}
                  {Array.from({ length: 3 }, (_, i) => (
                    <td key={`blank-${i}`} className="tv-cell tv-blank-cell" style={{ width: 120, minWidth: 120 }}></td>
                  ))}
                </tr>
              )
            })}
            {/* 3 blank rows with [+] button */}
            {Array.from({ length: 3 }, (_, r) => {
              const rowNum = numRows + r + 1
              const isFirstBlank = r === 0
              return (
                <tr key={`blank-${rowNum}`} className="tv-blank-row">
                  <th className="tv-row-header tv-blank-header" style={{ width: rowHeaderWidth, minWidth: rowHeaderWidth, maxWidth: rowHeaderWidth }}>
                    {isFirstBlank ? (
                      <button className="tv-add-row-btn" onClick={handleAddRow} title="新增一行">+</button>
                    ) : null}
                  </th>
                  {Array.from({ length: numCols }, (_, c) => (
                    <td key={c} className="tv-cell tv-blank-cell" style={{ width: 120, minWidth: 120 }}></td>
                  ))}
                  {/* 3 blank cells for extra columns */}
                  {Array.from({ length: 3 }, (_, i) => (
                    <td key={`blank-col-${i}`} className="tv-cell tv-blank-cell" style={{ width: 120, minWidth: 120 }}></td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="tv-sheet-tabs" ref={tabsRef}>
        {sheetIds.map(sid => (
          <div
            key={sid}
            className={`tv-tab ${sid === activeSheetId ? 'is-active' : ''}`}
            onClick={() => setActiveSheetId(sid)}
          >
            <span className="tv-tab-label">{truncate(getSheetTitle(sid), 12)}</span>
            {isAdmin && (
              <button
                className="tv-tab-edit-btn"
                title="重新命名"
                onClick={(e) => {
                  e.stopPropagation()
                  openRenameSheetModal(sid)
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a2.83 2.83 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
              </button>
            )}
            {isAdmin && (
              <button
                className="tv-tab-delete-btn"
                title="刪除工作表"
                onClick={(e) => {
                  e.stopPropagation()
                  openDeleteSheetModal(sid)
                }}
                disabled={isDeletingSheet}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            )}
          </div>
        ))}
        {isAdmin && (
          <button className="tv-tab tv-tab-add" title="新建立工作表" onClick={openCreateSheetModal}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
        )}
        {showCountdown && (
          <div className="tv-send-countdown" title="資料完成送出時間倒數">
            <svg className="tv-countdown-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span className="tv-countdown-time">{formatCountdown(countdown)}</span>
          </div>
        )}
      </div>

      {showSheetModal && (
        <div className="modal-overlay" onClick={closeSheetModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">{sheetModalMode === 'create' ? '新建立工作表' : '工作表名稱異動'}</div>
            <div className="modal-body">
              <label className="tv-sheet-modal-label">工作表名稱</label>
              <input
                type="text"
                className="admin-passcode-input tv-sheet-name-input"
                value={sheetModalName}
                onChange={(e) => setSheetModalName(e.target.value)}
                maxLength={50}
                onKeyDown={(e) => { if (e.key === 'Enter') confirmSheetModal() }}
                autoFocus
              />
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={closeSheetModal}>取消</button>
              <button className="modal-btn modal-btn-confirm" onClick={confirmSheetModal} disabled={isSubmittingSheet || !sheetModalName.trim()}>確定</button>
            </div>
          </div>
        </div>
      )}

      {showDeleteModal && deleteTargetSheetId && (
        <div className="modal-overlay" onClick={closeDeleteSheetModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">刪除工作表</div>
            <div className="modal-body">
              <p>確認要刪除工作表「{getSheetTitle(deleteTargetSheetId)}」？刪除後無法復原，並會同步影響其他節點中的內容。</p>
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={closeDeleteSheetModal}>取消</button>
              <button className="modal-btn modal-btn-confirm" onClick={confirmDeleteSheet} disabled={isDeletingSheet} style={{ background: '#d32f2f' }}>刪除</button>
            </div>
          </div>
        </div>
      )}

      {showPasscodeModal && (
        <div className="modal-overlay" onClick={handlePasscodeCancel}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">資料輸入密碼</div>
            <div className="modal-body">
              <p>請輸入發送用通關碼以送出資料：</p>
              <input
                type="password"
                className="admin-passcode-input"
                placeholder="輸入發送用通關碼"
                value={passcodeInput}
                onChange={(e) => { setPasscodeInput(e.target.value); setPasscodeError('') }}
                onKeyDown={(e) => { if (e.key === 'Enter') handlePasscodeConfirm() }}
                autoFocus
              />
              {passcodeError && <div className="tv-passcode-error">{passcodeError}</div>}
            </div>
            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={handlePasscodeCancel}>取消</button>
              <button className="modal-btn modal-btn-confirm" onClick={handlePasscodeConfirm} disabled={isSubmitting || isSubmittingSheet}>確定</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default TableView
