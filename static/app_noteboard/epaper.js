(function () {
    const qrContainer = document.getElementById('wifi-qrcode')
    if (!qrContainer) return

    const payload = qrContainer.dataset.qrPayload || ''
    if (!payload) return

    const renderFallback = () => {
        qrContainer.innerHTML = '<div class="qrcode-fallback">QRCode 生成失敗<br>請手動加入 Wi-Fi</div>'
    }

    const boxSize = qrContainer.offsetWidth || 210
    const qrSize = Math.max(boxSize - 20, 100)

    const renderQRCode = () => {
        try {
            new QRCode(qrContainer, {
                text: payload,
                width: qrSize,
                height: qrSize,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            })
            return true
        } catch (error) {
            return false
        }
    }
    if (typeof QRCode === 'undefined') {
        renderFallback()
        return
    }
    if (!renderQRCode()) {
        renderFallback()
    }
})()
