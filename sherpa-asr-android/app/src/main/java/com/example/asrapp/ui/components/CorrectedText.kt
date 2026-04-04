package com.example.asrapp.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.InlineTextContent
import androidx.compose.foundation.text.appendInlineContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.example.asrapp.network.model.DiffSpan
import com.example.asrapp.network.model.DiffType

/**
 * 带差异高亮的文本组件
 *
 * 显示纠正后的文本，并用不同样式标记修改部分：
 * - Phonetic: 红色删除线 + 绿色下划线
 * - Filler: 灰色删除线（表示删除）
 * - Grammar: 黄色背景
 */
@Composable
fun CorrectedText(
    original: String,
    corrected: String,
    corrections: List<DiffSpan>,
    modifier: Modifier = Modifier
) {
    val styledText = rememberCorrectedText(original, corrected, corrections)

    Text(
        text = styledText,
        style = MaterialTheme.typography.bodyLarge,
        modifier = modifier
    )
}

/**
 * 记住并计算带样式的文本
 */
@Composable
fun rememberCorrectedText(
    original: String,
    corrected: String,
    corrections: List<DiffSpan>
): AnnotatedString {
    return buildAnnotatedString {
        if (corrections.isEmpty()) {
            // 没有纠错，直接显示纠正后文本
            append(corrected)
            return@buildAnnotatedString
        }

        // 简化处理：直接显示纠正后文本，高亮所有修正部分
        // 因为服务端返回的索引基于原文，无法直接用于纠正后文本

        // 收集所有被修正的内容
        val correctedParts = corrections
            .filter { it.corrected.isNotEmpty() }
            .map { it.corrected }

        if (correctedParts.isEmpty()) {
            // 只有删除，没有添加
            append(corrected)
            return@buildAnnotatedString
        }

        // 简单策略：遍历纠正后文本，匹配修正部分并高亮
        var remainingText = corrected

        for (correction in corrections.filter { it.corrected.isNotEmpty() }) {
            val part = correction.corrected
            val idx = remainingText.indexOf(part)

            if (idx >= 0) {
                // 添加匹配部分之前的文本
                if (idx > 0) {
                    append(remainingText.substring(0, idx))
                }

                // 添加高亮的修正部分
                val diffStyle = when (correction.type) {
                    DiffType.PHONETIC.name -> SpanStyle(
                        color = MaterialTheme.colorScheme.primary,
                        background = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
                    )
                    DiffType.GRAMMAR.name -> SpanStyle(
                        background = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f)
                    )
                    DiffType.COMMAND.name -> SpanStyle(
                        color = MaterialTheme.colorScheme.secondary,
                        background = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.3f)
                    )
                    else -> null
                }

                if (diffStyle != null) {
                    withStyle(diffStyle) { append(part) }
                } else {
                    append(part)
                }

                remainingText = remainingText.substring(idx + part.length)
            }
        }

        // 添加剩余文本
        if (remainingText.isNotEmpty()) {
            append(remainingText)
        }
    }
}

/**
 * 差异图例
 */
@Composable
fun DiffLegend(modifier: Modifier = Modifier) {
    Text(
        text = buildAnnotatedString {
            append("差异说明：")
            append(" ")

            withStyle(SpanStyle(
                color = MaterialTheme.colorScheme.primary,
                background = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
            )) {
                append("同音字纠正")
            }
            append(" ")

            withStyle(SpanStyle(
                background = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f)
            )) {
                append("语法调整")
            }
            append(" ")

            withStyle(SpanStyle(
                color = MaterialTheme.colorScheme.secondary,
                background = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.3f)
            )) {
                append("命令解析")
            }
        },
        style = MaterialTheme.typography.bodySmall,
        modifier = modifier
    )
}

/**
 * 显示原文和纠正文的对比
 */
@Composable
fun BeforeAfterComparison(
    original: String,
    corrected: String,
    corrections: List<DiffSpan>,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        // 原文
        Text(
            text = "原文",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = original,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(Modifier.height(8.dp))

        // 纠正后
        Text(
            text = "纠正后",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.primary
        )
        CorrectedText(
            original = original,
            corrected = corrected,
            corrections = corrections
        )
    }
}
