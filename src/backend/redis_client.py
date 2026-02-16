"""
Redis client for distributed resilience coordination.

COMPATIBILITY SHIM: This module is maintained for backward compatibility
during incremental migration to the new storage abstraction layer.
New code should import from backend.storage instead.

Supports:
- Leader election with TTL-based expiry
- State publishing to cluster
- Vote collection for consensus
- Cluster state aggregation
- TLS/SSL encrypted connections (rediss://)

Migration path:
    # Old (still works):
    from backend.redis_client import RedisClient
    
    # New (preferred):
    from backend.storage import Storage, RedisAdapter
    storage: Storage = RedisAdapter.from_config(config)
"""

import ssl
import redis.asyncio as aioredis
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from urllib.parse import urlparse

# Import timeout handling
from core.timeout_handler import get_timeout_config
from core.tls_config import get_tls_config, is_tls_required, create_ssl_context
from core.tls_enforcement import TLSValidator, TLSEnforcementError
import asyncio

# Re-export storage components for compatibility
from backend.storage import Storage, RedisAdapter, MemoryStorage

logger = logging.getLogger(__name__)


# Compatibility exports
__all__ = ["RedisClient", "Storage", "RedisAdapter", "MemoryStorage"]


class RedisClient:
    """Redis client for distributed coordination with TLS support."""

    def __init__(
        self, 
        redis_url: str = "redis://localhost:6379", 
        timeout: float = None,
        use_tls: Optional[bool] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        service_name: Optional[str] = "redis"
    ):
        """Initialize Redis client with TLS support.

        Args:
            redis_url: Redis connection URL (default: localhost:6379)
                       Use rediss:// for TLS-encrypted connections
            timeout: Default timeout for operations (uses env config if None)
            use_tls: Force TLS usage (None = auto-detect from URL and config)
            ssl_context: Optional SSL context for custom TLS configuration
            service_name: Service name for TLS configuration lookup
        """
        self.redis_url = redis_url
        self.redis = None
        self.connected = False
        self.timeout = timeout or get_timeout_config().redis_timeout
        self.service_name = service_name
        self._ssl_context = ssl_context
        
        # TLS configuration
        self.tls_config = get_tls_config(service_name)
        self.tls_required = is_tls_required(service_name) if use_tls is None else use_tls
        
        # Validate and potentially upgrade URL to TLS
        self.redis_url = self._validate_and_upgrade_url(redis_url)
        
        logger.info(f"RedisClient initialized with URL: {self._sanitize_url(self.redis_url)}")
    
    def _sanitize_url(self, url: str) -> str:
        """Sanitize URL for logging (hide credentials)."""
        try:
            parsed = urlparse(url)
            if parsed.password:
                # Replace password with ***
                safe_url = url.replace(f":{parsed.password}@", ":***@")
                return safe_url
        except Exception:
            pass
        return url
    
    def _validate_and_upgrade_url(self, url: str) -> str:
        """
        Validate Redis URL and upgrade to TLS if required.
        
        Args:
            url: Redis URL to validate
            
        Returns:
            Validated (and potentially upgraded) URL
            
        Raises:
            TLSEnforcementError: If unencrypted Redis is used when TLS is required
        """
        parsed = urlparse(url)
        
        # Check if URL already uses TLS
        if parsed.scheme == "rediss":
            logger.debug("Redis URL uses TLS (rediss://)")
            return url
        
        # Check if URL uses unencrypted Redis
        if parsed.scheme == "redis":
            if self.tls_required:
                # Upgrade to TLS
                tls_url = url.replace("redis://", "rediss://", 1)
                logger.warning(
                    f"Auto-upgraded Redis URL from redis:// to rediss:// "
                    f"due to TLS enforcement requirement"
                )
                return tls_url
            else:
                logger.warning(
                    f"Redis URL uses unencrypted connection (redis://). "
                    f"Consider using rediss:// for production environments."
                )
                return url
        
        # Unknown scheme - assume Redis and add scheme
        if not parsed.scheme:
            if self.tls_required:
                logger.info(f"Adding rediss:// scheme to URL (TLS required): {url}")
                return f"rediss://{url}"
            else:
                logger.info(f"Adding redis:// scheme to URL: {url}")
                return f"redis://{url}"
        
        return url
    
    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        Create SSL context for Redis TLS connections.
        
        Returns:
            SSLContext or None if TLS is not enabled
        """
        if not self.tls_config.enabled:
            return None
        
        # Use provided SSL context if available
        if self._ssl_context:
            return self._ssl_context
        
        try:
            return create_ssl_context(self.service_name)
        except Exception as e:
            if self.tls_required:
                raise TLSEnforcementError(f"Failed to create SSL context for Redis: {e}")
            logger.warning(f"Could not create SSL context, using default: {e}")
            return ssl.create_default_context()


    async def connect(self) -> bool:
        """Establish connection to Redis with TLS support.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Determine if we need SSL/TLS
            parsed = urlparse(self.redis_url)
            use_ssl = parsed.scheme == "rediss"
            
            connection_kwargs = {}
            
            if use_ssl:
                ssl_context = self._create_ssl_context()
                if ssl_context:
                    connection_kwargs["ssl"] = ssl_context
                    logger.debug("Using TLS for Redis connection")
            
            # Create Redis connection
            self.redis = await aioredis.from_url(
                self.redis_url,
                **connection_kwargs
            )
            
            # Test connection
            await self.redis.ping()
            self.connected = True
            
            # Log connection success (with TLS info)
            tls_status = " (TLS enabled)" if use_ssl else " (unencrypted)"
            logger.info(f"Connected to Redis{tls_status}: {self._sanitize_url(self.redis_url)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.connected = False
            return False


    async def close(self):
        """Close Redis connection."""
        if self.redis:
            try:
                await self.redis.close()
                self.connected = False
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")

    async def leader_election(self, instance_id: str, ttl: int = 30) -> bool:
        """Attempt leader election with TTL-based expiry and timeout protection.

        Uses SET with NX (only if not exists) to ensure only one leader.
        TTL ensures automatic failover on instance failure.

        Args:
            instance_id: Unique instance identifier
            ttl: Time to live for leadership (seconds, default: 30)

        Returns:
            True if elected leader, False if leader already exists
        """
        if not self.connected:
            logger.warning("Redis not connected, cannot perform leader election")
            return False

        try:
            # Wrap Redis operation with timeout
            result = await asyncio.wait_for(
                self.redis.set(
                    "astra:resilience:leader",
                    instance_id,
                    nx=True,  # Only set if key doesn't exist
                    ex=ttl,  # Set expiry
                ),
                timeout=self.timeout
            )
            if result:
                logger.info(f"Instance {instance_id} elected as leader (TTL: {ttl}s)")
            else:
                logger.debug(f"Instance {instance_id} did not win leader election")
            return result
        except asyncio.TimeoutError:
            logger.error(f"Leader election timeout ({self.timeout}s exceeded)")
            return False
        except Exception as e:
            logger.error(f"Leader election failed: {e}")
            return False

    async def renew_leadership(self, instance_id: str, ttl: int = 30) -> bool:
        """Renew leadership TTL if currently leader.

        Uses atomic Lua script to prevent TOCTOU race condition.
        Script checks if key value equals instance_id, then atomically sets TTL.

        Args:
            instance_id: Current instance ID (must match leader)
            ttl: New TTL (seconds)

        Returns:
            True if renewed, False if not leader
        """
        if not self.connected:
            return False

        try:
            # Lua script for atomic check-and-expire operation
            # Returns 1 (true) if value matches and TTL was set
            # Returns 0 (false) if value doesn't match
            lua_script = """
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                redis.call("EXPIRE", KEYS[1], ARGV[2])
                return 1
            else
                return 0
            end
            """

            # Execute script atomically
            result = await self.redis.eval(
                lua_script,
                1,  # number of keys
                "astra:resilience:leader",  # KEYS[1]
                instance_id,  # ARGV[1]
                ttl,  # ARGV[2]
            )

            renewed = bool(result)
            if renewed:
                logger.debug(f"Leadership renewed for {instance_id} (TTL: {ttl}s)")
            else:
                logger.debug(
                    f"Leadership renewal failed for {instance_id} (not current leader)"
                )

            return renewed
        except Exception as e:
            logger.error(f"Failed to renew leadership: {e}")
            return False

    async def get_leader(self) -> Optional[str]:
        """Get current leader instance ID.

        Returns:
            Instance ID of current leader, or None if no leader
        """
        if not self.connected:
            return None

        try:
            leader = await self.redis.get("astra:resilience:leader")
            return leader.decode() if leader else None
        except Exception as e:
            logger.error(f"Failed to get leader: {e}")
            return None

    async def publish_state(self, channel: str, state: Dict[str, Any]) -> int:
        """Publish resilience state to cluster via pub/sub.

        Args:
            channel: Channel name (e.g., "astra:resilience:state")
            state: State dictionary to publish

        Returns:
            Number of subscribers that received the message
        """
        if not self.connected:
            logger.warning("Redis not connected, cannot publish state")
            return 0

        try:
            subscribers = await self.redis.publish(channel, json.dumps(state))
            logger.debug(f"Published state to {subscribers} subscribers on {channel}")
            return subscribers
        except Exception as e:
            logger.error(f"Failed to publish state: {e}")
            return 0

    async def register_vote(
        self, instance_id: str, vote: Dict[str, Any], ttl: int = 30
    ) -> bool:
        """Register instance vote in cluster consensus.

        Args:
            instance_id: Instance ID voting
            vote: Vote data (e.g., circuit breaker state, fallback mode)
            ttl: Vote expiry time (seconds)

        Returns:
            True if registered, False otherwise
        """
        if not self.connected:
            return False

        try:
            key = f"astra:resilience:vote:{instance_id}"
            # Create shallow copy to avoid mutating caller's dict
            vote_copy = dict(vote)
            vote_copy["timestamp"] = datetime.utcnow().isoformat()
            await self.redis.set(key, json.dumps(vote_copy), ex=ttl)
            logger.debug(f"Registered vote from {instance_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register vote: {e}")
            return False

    async def get_cluster_votes(
        self, prefix: str = "astra:resilience:vote"
    ) -> Dict[str, Any]:
        """Retrieve all instance votes for consensus using non-blocking SCAN.

        Args:
            prefix: Key prefix for votes (default: astra:resilience:vote)

        Returns:
            Dict mapping instance_id to vote data
        """
        if not self.connected:
            return {}

        try:
            # Use SCAN to non-blocking retrieve keys (avoids O(N) blocking)
            pattern = f"{prefix}:*"
            cursor = 0
            keys = []

            # SCAN loop accumulates keys until cursor returns to 0
            while True:
                cursor, batch_keys = await self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,  # Process 100 keys at a time
                )
                keys.extend(batch_keys)
                if cursor == 0:
                    break  # Iteration complete

            if not keys:
                logger.debug("No votes found in cluster")
                return {}

            # Batch get all values
            pipe = self.redis.pipeline()
            for key in keys:
                pipe.get(key)
            values = await pipe.execute()

            # Parse votes
            votes = {}
            for key, value in zip(keys, values):
                if value:
                    try:
                        instance_id = key.decode().split(":")[-1]
                        votes[instance_id] = json.loads(value)
                    except (json.JSONDecodeError, IndexError) as e:
                        logger.warning(f"Failed to parse vote from {key}: {e}")

            logger.debug(f"Retrieved {len(votes)} votes from cluster")
            return votes
        except asyncio.TimeoutError:
            logger.error(f"Get cluster votes timeout ({self.timeout}s exceeded)")
            return {}
        except Exception as e:
            logger.error(f"Failed to get cluster votes: {e}")
            return {}

    async def get_instance_health(self, instance_id: str) -> Optional[Dict]:
        """Get last known health state of instance.

        Args:
            instance_id: Instance ID to query

        Returns:
            Health state dict or None if not found
        """
        if not self.connected:
            return None

        try:
            key = f"astra:health:{instance_id}"
            health = await self.redis.get(key)
            if health:
                return json.loads(health)
            return None
        except Exception as e:
            logger.error(f"Failed to get health for {instance_id}: {e}")
            return None

    async def publish_health(
        self, instance_id: str, health: Dict[str, Any], ttl: int = 60
    ) -> bool:
        """Publish instance health state to cluster.

        Args:
            instance_id: Instance ID publishing health
            health: Health state dictionary
            ttl: Health data TTL (seconds)

        Returns:
            True if published, False otherwise
        """
        if not self.connected:
            return False

        try:
            key = f"astra:health:{instance_id}"
            # Create shallow copy to avoid mutating caller's dict
            health_copy = dict(health)
            health_copy["timestamp"] = datetime.utcnow().isoformat()
            await self.redis.set(key, json.dumps(health_copy), ex=ttl)
            logger.debug(f"Published health for {instance_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish health: {e}")
            return False

    async def get_all_instance_health(self) -> Dict[str, Dict]:
        """Get health states of all instances using non-blocking SCAN.

        Returns:
            Dict mapping instance_id to health state
        """
        if not self.connected:
            return {}

        try:
            # Use SCAN to non-blocking retrieve keys (avoids O(N) blocking)
            pattern = "astra:health:*"
            cursor = 0
            keys = []

            # SCAN loop accumulates keys until cursor returns to 0
            while True:
                cursor, batch_keys = await self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,  # Process 100 keys at a time
                )
                keys.extend(batch_keys)
                if cursor == 0:
                    break  # Iteration complete

            if not keys:
                return {}

            pipe = self.redis.pipeline()
            for key in keys:
                pipe.get(key)
            values = await pipe.execute()

            health_states = {}
            for key, value in zip(keys, values):
                if value:
                    try:
                        instance_id = key.decode().split(":")[-1]
                        health_states[instance_id] = json.loads(value)
                    except (json.JSONDecodeError, IndexError) as e:
                        logger.warning(f"Failed to parse health from {key}: {e}")

            logger.debug(f"Retrieved health for {len(health_states)} instances")
            return health_states
        except Exception as e:
            logger.error(f"Failed to get all instance health: {e}")
            return {}

    async def clear_stale_votes(self, prefix: str = "astra:resilience:vote") -> int:
        """Remove expired/stale votes (cleanup) using non-blocking SCAN.

        Args:
            prefix: Key prefix for votes

        Returns:
            Number of votes cleared
        """
        if not self.connected:
            return 0

        try:
            # Use SCAN to non-blocking retrieve keys (avoids O(N) blocking)
            pattern = f"{prefix}:*"
            cursor = 0
            keys = []

            # SCAN loop accumulates keys until cursor returns to 0
            while True:
                cursor, batch_keys = await self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,  # Process 100 keys at a time
                )
                keys.extend(batch_keys)
                if cursor == 0:
                    break  # Iteration complete

            if not keys:
                return 0

            pipe = self.redis.pipeline()
            for key in keys:
                pipe.delete(key)
            results = await pipe.execute()

            cleared = sum(1 for r in results if r)
            if cleared > 0:
                logger.debug(f"Cleared {cleared} stale votes")
            return cleared
        except Exception as e:
            logger.error(f"Failed to clear stale votes: {e}")
            return 0

    async def subscribe_to_channel(self, channel: str):
        """Subscribe to pub/sub channel (returns pubsub object).

        Args:
            channel: Channel name to subscribe to

        Returns:
            Subscription object for listening to messages
        """
        if not self.connected:
            return None

        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to channel: {channel}")
            return pubsub
        except Exception as e:
            logger.error(f"Failed to subscribe to {channel}: {e}")
            return None

    async def health_check(self) -> bool:
        """Perform health check on Redis connection.

        Returns:
            True if healthy, False otherwise
        """
        if not self.connected:
            return False

        try:
            await self.redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            self.connected = False
            return False
