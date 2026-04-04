package com.example.asrapp

import android.app.Application
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.example.asrapp.model.AsrModelLoader
import com.example.asrapp.model.TtsModelLoader
import com.example.asrapp.viewmodel.AsrViewModel

class AsrApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        // Copy assets to filesDir on first launch (background thread)
        // Actual model initialisation happens lazily in ViewModel
        AsrModelLoader.prepareAssets(this)
        TtsModelLoader.prepareAssets(this)

        // Setup network monitoring
        setupNetworkMonitoring()
    }

    private fun setupNetworkMonitoring() {
        val connectivityManager = getSystemService(ConnectivityManager::class.java)
        val networkRequest = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        connectivityManager.registerNetworkCallback(
            networkRequest,
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    // Network available
                    NetworkMonitor.setAvailable(true)
                }

                override fun onLost(network: Network) {
                    // Network lost
                    NetworkMonitor.setAvailable(false)
                }

                override fun onCapabilitiesChanged(
                    network: Network,
                    networkCapabilities: NetworkCapabilities
                ) {
                    val hasInternet = networkCapabilities
                        .hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    NetworkMonitor.setAvailable(hasInternet)
                }
            }
        )
    }
}

/**
 * ViewModelFactory for AsrViewModel
 */
class AsrViewModelFactory(
    private val application: Application
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(AsrViewModel::class.java)) {
            return AsrViewModel(application) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class: ${modelClass.name}")
    }
}

/**
 * 网络状态监控单例
 */
object NetworkMonitor {
    private val TAG = "NetworkMonitor"
    private var isAvailable = true
    private val listeners = mutableSetOf<(Boolean) -> Unit>()

    fun setAvailable(available: Boolean) {
        if (isAvailable != available) {
            android.util.Log.i(TAG, "Network availability changed: $isAvailable → $available")
            isAvailable = available
            listeners.forEach { it(available) }
        }
    }

    fun getAvailable(): Boolean = isAvailable

    fun addListener(listener: (Boolean) -> Unit) {
        listeners.add(listener)
        android.util.Log.d(TAG, "addListener: current network available=$isAvailable, listeners=${listeners.size}")
        // 立即通知当前状态
        listener(isAvailable)
    }

    fun removeListener(listener: (Boolean) -> Unit) {
        listeners.remove(listener)
        android.util.Log.d(TAG, "removeListener: remaining listeners=${listeners.size}")
    }
}
