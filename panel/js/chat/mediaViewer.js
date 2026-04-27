export function normalizePreviewIndex(index, length) {
    if (!length) return 0

    const numericIndex = Number(index)
    if (!Number.isFinite(numericIndex)) return 0

    return Math.max(0, Math.min(length - 1, Math.trunc(numericIndex)))
}

export function isValidPreviewIndex(index, length) {
    const numericIndex = Number(index)
    return Number.isFinite(numericIndex) && numericIndex >= 0 && Math.trunc(numericIndex) < length
}
