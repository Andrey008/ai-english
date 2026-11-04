package com.aienglish.companion.data.api

/** Every server response the UI layer needs to branch on, distinguishable —
 * a 409/404/422 is a normal, expected outcome for this app (duplicate
 * character id, deleted-then-fetched, bad form data), not an exception to
 * throw and catch blindly. */
sealed class ApiResult<out T> {
    data class Success<T>(val data: T) : ApiResult<T>()
    data class HttpError(val code: Int, val body: String?) : ApiResult<Nothing>()
    data class NetworkError(val cause: Throwable) : ApiResult<Nothing>()
}
