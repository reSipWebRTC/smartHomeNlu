package com.example.asrapp.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.asrapp.viewmodel.CommandInfo
import kotlin.math.max

/**
 * 智能家居命令卡片
 *
 * 显示解析到的命令列表
 */
@Composable
fun CommandCards(
    commands: List<CommandInfo>,
    modifier: Modifier = Modifier
) {
    if (commands.isEmpty()) return

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // 标题
        Text(
            text = "📌 检测到 ${commands.size} 条命令",
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.primary
        )

        // 命令列表
        commands.forEach { command ->
            CommandItem(command = command)
        }
    }
}

/**
 * 单个命令项
 */
@Composable
fun CommandItem(
    command: CommandInfo,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.3f),
        tonalElevation = 2.dp
    ) {
        Row(
            modifier = Modifier
                .padding(12.dp)
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 图标
            Icon(
                imageVector = Icons.Default.CheckCircle,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(20.dp)
            )

            Spacer(Modifier.width(12.dp))

            // 命令描述
            Text(
                text = command.description,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface
            )

            Spacer(Modifier.weight(1f))

            // 设备图标（根据设备类型显示不同图标）
            DeviceIcon(device = command.device)
        }
    }
}

/**
 * 设备图标
 */
@Composable
fun DeviceIcon(device: String) {
    val icon = when {
        device.contains("灯") -> Icons.Default.Lightbulb
        else -> Icons.Default.CheckCircle
    }

    val iconColor = when {
        device.contains("灯") -> Color(0xFFFFD700) // 金色
        device.contains("空调") -> Color(0xFF87CEEB) // 天蓝色
        device.contains("窗帘") -> Color(0xFFDDA0DD) // 梅红色
        else -> MaterialTheme.colorScheme.secondary
    }

    Surface(
        shape = RoundedCornerShape(8.dp),
        color = iconColor.copy(alpha = 0.2f),
        modifier = Modifier.size(32.dp)
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = device,
                tint = iconColor,
                modifier = Modifier.size(18.dp)
            )
        }
    }
}

/**
 * 紧凑型命令列表（用于底部显示）
 */
@Composable
fun CompactCommandList(
    commands: List<CommandInfo>,
    modifier: Modifier = Modifier
) {
    if (commands.isEmpty()) return

    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        tonalElevation = 4.dp
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text(
                text = "识别的命令",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            commands.forEach { command ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Icon(
                        imageVector = Icons.Default.CheckCircle,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(14.dp)
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        text = command.description,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}

/**
 * 纠错状态指示器
 */
@Composable
fun CorrectionStatusIndicator(
    isCorrecting: Boolean,
    correctionCount: Int,
    processingTimeMs: Float,
    modifier: Modifier = Modifier
) {
    if (!isCorrecting && correctionCount == 0) return

    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        color = when {
            isCorrecting -> MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f)
            else -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
        }
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (isCorrecting) {
                // 加载中
                CircularProgressIndicator(
                    modifier = Modifier.size(14.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.tertiary
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    text = "纠正中...",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            } else {
                // 完成
                Icon(
                    imageVector = Icons.Default.CheckCircle,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(14.dp)
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    text = "已纠正 $correctionCount 处 ⚡ ${processingTimeMs.toInt()}ms",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary
                )
            }
        }
    }
}
