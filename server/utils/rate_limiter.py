"""Rate limiter with exponential backoff and circuit breaker for provider API calls.

Ensures providers respect rate limits by tracking call timestamps and
applying configurable delays between requests. Supports exponential
backoff on errors with jitter to prevent thundering herd.

The circuit breaker prevents hammering unreachable APIs: after a
configurable number of consecutive failures the circuit opens and all
calls are rejected immediately for an escalating cooldown period.  A
single probe is allowed when the cooldown expires (half-open state).
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Circuit breaker states
_CLOSED = "closed"
_OPEN = "open"
_HALF_OPEN = "half_open"


class RateLimiter:
    """Token-bucket-style rate limiter with backoff and circuit breaker.

    Args:
        calls_per_minute: Maximum API calls allowed per minute.
        min_interval: Minimum seconds between consecutive calls.
        name: Identifier for logging purposes.
        circuit_threshold: Consecutive errors before the circuit opens.
        circuit_base_cooldown: Initial cooldown in seconds when the circuit
            opens.  Doubles on each successive open, capped at
            ``circuit_max_cooldown``.
        circuit_max_cooldown: Upper bound on circuit-open cooldown.
    """

    def __init__(
        self,
        calls_per_minute: int = 10,
        min_interval: float = 2.0,
        name: str = "provider",
        circuit_threshold: int = 5,
        circuit_base_cooldown: float = 60.0,
        circuit_max_cooldown: float = 900.0,
    ) -> None:
        self._calls_per_minute = calls_per_minute
        self._min_interval = min_interval
        self._name = name
        self._last_call: float = 0.0
        self._call_timestamps: list[float] = []
        self._backoff_until: float = 0.0
        self._consecutive_errors = 0
        self._lock = asyncio.Lock()

        # Circuit breaker state
        self._circuit_state: str = _CLOSED
        self._circuit_threshold = circuit_threshold
        self._circuit_base_cooldown = circuit_base_cooldown
        self._circuit_max_cooldown = circuit_max_cooldown
        self._circuit_open_until: float = 0.0
        self._circuit_open_count: int = 0  # how many times circuit has opened

    async def acquire(self) -> None:
        """Wait until a call is permitted by the rate limiter.

        Blocks if the rate limit has been reached or if in a backoff period.

        Raises:
            RuntimeError: If the circuit breaker is open and the cooldown
                has not yet expired.
        """
        async with self._lock:
            now = time.monotonic()

            # --- Circuit breaker gate ---
            if self._circuit_state == _OPEN:
                if now < self._circuit_open_until:
                    remaining = self._circuit_open_until - now
                    raise RuntimeError(
                        f"{self._name}: circuit breaker OPEN — "
                        f"rejecting call ({remaining:.0f}s remaining)"
                    )
                # Cooldown expired — allow one probe
                self._circuit_state = _HALF_OPEN
                logger.info(
                    "%s circuit breaker: transitioning to HALF_OPEN (probe)",
                    self._name,
                )

            # Check backoff
            if now < self._backoff_until:
                wait = self._backoff_until - now
                logger.info(
                    "%s rate limiter: backing off for %.1fs", self._name, wait
                )
                await asyncio.sleep(wait)
                now = time.monotonic()

            # Enforce minimum interval
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                await asyncio.sleep(wait)
                now = time.monotonic()

            # Enforce calls-per-minute limit
            cutoff = now - 60.0
            self._call_timestamps = [
                t for t in self._call_timestamps if t > cutoff
            ]
            if len(self._call_timestamps) >= self._calls_per_minute:
                # Wait until the oldest call falls outside the window
                oldest = self._call_timestamps[0]
                wait = 60.0 - (now - oldest) + 0.1
                if wait > 0:
                    logger.info(
                        "%s rate limiter: calls-per-minute limit reached, "
                        "waiting %.1fs",
                        self._name,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    now = time.monotonic()

            self._call_timestamps.append(now)
            self._last_call = now

    def record_success(self) -> None:
        """Record a successful API call, resetting error backoff and circuit."""
        if self._circuit_state == _HALF_OPEN:
            logger.info(
                "%s circuit breaker: probe succeeded — circuit CLOSED",
                self._name,
            )
        self._consecutive_errors = 0
        self._backoff_until = 0.0
        self._circuit_state = _CLOSED
        self._circuit_open_count = 0
        self._circuit_open_until = 0.0

    def record_error(self) -> None:
        """Record a failed API call, increasing backoff and potentially opening the circuit.

        Uses exponential backoff with jitter: base * 2^errors + jitter.
        Caps at 5 minutes for normal backoff.  If the circuit breaker
        threshold is reached the circuit opens with an escalating cooldown.
        """
        self._consecutive_errors += 1

        # If we were probing in half-open state, re-open immediately
        if self._circuit_state == _HALF_OPEN:
            self._open_circuit("half-open probe failed")
            return

        # Normal exponential backoff
        base_delay = 5.0  # seconds
        max_delay = 300.0  # 5 minutes
        delay = min(
            base_delay * (2 ** (self._consecutive_errors - 1)), max_delay
        )
        jitter = random.uniform(0, delay * 0.1)
        self._backoff_until = time.monotonic() + delay + jitter
        logger.warning(
            "%s rate limiter: error #%d, backing off %.1fs",
            self._name,
            self._consecutive_errors,
            delay + jitter,
        )

        # Open circuit if threshold reached
        if self._consecutive_errors >= self._circuit_threshold:
            self._open_circuit(
                f"{self._consecutive_errors} consecutive errors"
            )

    def _open_circuit(self, reason: str) -> None:
        """Transition to OPEN state with escalating cooldown.

        Args:
            reason: Human-readable reason for opening.
        """
        self._circuit_state = _OPEN
        self._circuit_open_count += 1
        cooldown = min(
            self._circuit_base_cooldown * (2 ** (self._circuit_open_count - 1)),
            self._circuit_max_cooldown,
        )
        jitter = random.uniform(0, cooldown * 0.1)
        self._circuit_open_until = time.monotonic() + cooldown + jitter
        logger.warning(
            "%s circuit breaker: OPEN (%s) — rejecting calls for %.0fs "
            "(open count: %d)",
            self._name,
            reason,
            cooldown + jitter,
            self._circuit_open_count,
        )

    @property
    def circuit_state(self) -> str:
        """Current circuit breaker state: 'closed', 'open', or 'half_open'."""
        # Auto-transition from open to half_open if cooldown expired
        if (
            self._circuit_state == _OPEN
            and time.monotonic() >= self._circuit_open_until
        ):
            return _HALF_OPEN
        return self._circuit_state

    @property
    def circuit_open(self) -> bool:
        """Whether the circuit is open (calls will be rejected)."""
        return (
            self._circuit_state == _OPEN
            and time.monotonic() < self._circuit_open_until
        )

    @property
    def consecutive_errors(self) -> int:
        """Number of consecutive errors since last success."""
        return self._consecutive_errors

    @property
    def is_backing_off(self) -> bool:
        """Whether the limiter is currently in a backoff or circuit-open period."""
        if self.circuit_open:
            return True
        return time.monotonic() < self._backoff_until


async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    rate_limiter: RateLimiter | None = None,
    operation_name: str = "operation",
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry and exponential backoff.

    Args:
        func: The async function to call.
        *args: Positional arguments for func.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds before first retry.
        max_delay: Maximum delay between retries.
        rate_limiter: Optional RateLimiter to acquire before each attempt.
        operation_name: Name for logging.
        **kwargs: Keyword arguments for func.

    Returns:
        The result of func.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            if rate_limiter:
                await rate_limiter.acquire()

            result = await func(*args, **kwargs)

            if rate_limiter:
                rate_limiter.record_success()

            return result

        except RuntimeError as exc:
            # If the circuit breaker rejected the call, propagate
            # immediately — retrying would just hit the same gate.
            if rate_limiter and rate_limiter.circuit_open:
                logger.info(
                    "%s skipped — circuit breaker open", operation_name
                )
                raise

            last_exc = exc
            if rate_limiter:
                rate_limiter.record_error()

            if attempt < max_retries:
                delay = min(base_delay * (2**attempt), max_delay)
                jitter = random.uniform(0, delay * 0.2)
                total_delay = delay + jitter
                logger.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    operation_name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    total_delay,
                )
                await asyncio.sleep(total_delay)
            else:
                logger.error(
                    "%s failed after %d attempts: %s",
                    operation_name,
                    max_retries + 1,
                    exc,
                )

        except Exception as exc:
            last_exc = exc

            if rate_limiter:
                rate_limiter.record_error()

            if attempt < max_retries:
                delay = min(base_delay * (2**attempt), max_delay)
                jitter = random.uniform(0, delay * 0.2)
                total_delay = delay + jitter
                logger.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    operation_name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    total_delay,
                )
                await asyncio.sleep(total_delay)
            else:
                logger.error(
                    "%s failed after %d attempts: %s",
                    operation_name,
                    max_retries + 1,
                    exc,
                )

    raise last_exc  # type: ignore[misc]
