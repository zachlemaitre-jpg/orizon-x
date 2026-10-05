package com.orizonx.client.protocol

fun hex(text: String): ByteArray = text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
