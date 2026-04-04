package com.example.asrapp.utils

/**
 * Removes Chinese filler words and meaningless repetitions from ASR output.
 *
 * Examples
 *   "啊啊你好啊啊"     → "你好"
 *   "嗯嗯，我想订票"   → "我想订票"
 *   "那个那个帮我查一下" → "帮我查一下"
 *   "你好啊"           → "你好啊"   (trailing particle preserved)
 */
object FillerWordFilter {

    // Standalone filler words (only removed when they are the entire token,
    // i.e. surrounded by punctuation, whitespace, or start/end of string)
    private val STANDALONE_FILLERS = setOf(
        "啊", "啊啊", "啊啊啊",
        "嗯", "嗯嗯", "嗯嗯嗯",
        "哦", "哦哦",
        "呃", "呃呃",
        "哎", "哎哎",
        "呢",  "嘛",  "诶",  "唉", "喂", "哼",
        "那个那个", "这个这个",
        "就是就是", "然后然后"
    )

    // CJK character repeated 3+ times → pure filler (e.g. "啊啊啊啊")
    // But only for known filler characters; content words are left alone.
    private val FILLER_CHARS   = setOf('啊', '嗯', '哦', '呃', '哎', '唉')
    private val REPEAT_FILLER  = Regex("""([啊嗯哦呃哎唉])\1{2,}""")

    // Repeated short phrase (2–6 CJK chars), e.g. "你好你好" → "你好"
    private val REPEAT_PHRASE  = Regex("""([\u4e00-\u9fa5]{2,6})\1+""")

    // Leading filler before real content
    private val LEADING_FILLER = Regex("""^([啊嗯哦呃哎唉]+)[，。！？\s]*""")
    // Trailing filler after real content
    private val TRAILING_FILLER = Regex("""[，。！？\s]*([啊嗯哦呃哎唉]{2,})$""")

    // Boundary pattern reused for standalone removal
    private val BOUNDARY = """(?<=[，。！？\s]|^)"""
    private val END_BOUND = """(?=[，。！？\s]|$)"""

    fun clean(input: String): String {
        var s = input.trim()

        // 1. Remove multi-repeat filler characters (啊啊啊 → "")
        s = REPEAT_FILLER.replace(s, "")

        // 2. Deduplicate repeated content phrases (你好你好 → 你好)
        s = REPEAT_PHRASE.replace(s) { it.groupValues[1] }

        // 3. Remove leading filler
        s = LEADING_FILLER.replace(s, "")

        // 4. Remove trailing filler (2+ chars only, so "你好啊" is safe)
        s = TRAILING_FILLER.replace(s, "")

        // 5. Remove standalone filler tokens surrounded by punctuation/boundary
        STANDALONE_FILLERS.forEach { filler ->
            s = s.replace(
                Regex("$BOUNDARY${Regex.escape(filler)}$END_BOUND"), ""
            )
        }

        // 6. Normalise leftover punctuation clutter
        s = s.replace(Regex("""[，。！？\s]{2,}"""), "，")
            .trim('，', '。', ' ', '　')

        return s
    }
}
