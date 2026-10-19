package com.orizonx.client.actions

/**
 * Least-recently-used cache of decoded images keyed by the sha1 id the PC announces (cover art and app icons share it).
 * Both [put] and [get] mark an entry as most recently used; going over [capacity] drops the least recently used one
 * that is not pinned (the images on screen), so the cache may briefly exceed [capacity] when everything is pinned.
 * Not thread-safe: the owner serialises access.
 */
class ImageLru<V : Any>(val capacity: Int = DEFAULT_CAPACITY) {
    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    private val map = LinkedHashMap<String, V>(capacity + 1, 0.75f, true)

    val size: Int get() = map.size

    fun put(id: String, value: V, pinned: Set<String> = emptySet()) {
        map[id] = value
        while (map.size > capacity) {
            val victim = map.keys.firstOrNull { it != id && it !in pinned } ?: break
            map.remove(victim)
        }
    }

    /** The image for [id] (now the most recently used), or null. */
    operator fun get(id: String): V? = map[id]

    /** Ids from least to most recently used; reading them does not change the order. */
    fun keys(): List<String> = map.keys.toList()

    /** Immutable copy for the UI; reading it does not touch the recency. */
    fun snapshot(): Map<String, V> = LinkedHashMap(map)

    fun clear() = map.clear()

    companion object {
        const val DEFAULT_CAPACITY = 16
    }
}
