export async function copyText(text) {
  if (!text) {
    throw new Error('empty_text')
  }

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Some browsers expose Clipboard API but still reject writes because of
      // permission policy, embedded context, or inconsistent user-gesture checks.
      // Fall back to the legacy copy path instead of surfacing a false failure.
    }
  }

  fallbackCopyText(text)
}

function fallbackCopyText(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '-1000px'
  textarea.style.left = '-1000px'
  textarea.style.opacity = '0'

  document.body.appendChild(textarea)

  const activeElement = document.activeElement
  const selection = document.getSelection()
  const originalRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null

  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)

  const successful = document.execCommand('copy')

  document.body.removeChild(textarea)

  if (originalRange && selection) {
    selection.removeAllRanges()
    selection.addRange(originalRange)
  }

  if (activeElement && typeof activeElement.focus === 'function') {
    activeElement.focus()
  }

  if (!successful) {
    throw new Error('copy_failed')
  }
}
