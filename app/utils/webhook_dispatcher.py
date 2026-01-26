"""
Webhook dispatcher utility for sending webhook events to external systems.

This module handles:
- Dispatching webhook events asynchronously
- HMAC-SHA256 signature generation
- Retry logic with exponential backoff
- Rate limiting per webhook
- Delivery logging
"""
import hashlib
import hmac
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from functools import wraps

import requests
from flask import current_app

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    """Handles webhook event dispatching with retry logic."""
    
    # Singleton instance
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._rate_limiters: Dict[int, dict] = {}  # webhook_id -> {last_request, request_count}
        self._executor_lock = threading.Lock()
        
    def generate_signature(self, payload: str, secret: str) -> str:
        """
        Generate HMAC-SHA256 signature for webhook payload.
        
        Args:
            payload: JSON payload string
            secret: Webhook secret key
            
        Returns:
            Hex-encoded signature
        """
        return hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _check_rate_limit(self, webhook_id: int, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """
        Check if webhook is within rate limits.
        
        Args:
            webhook_id: Webhook ID
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
            
        Returns:
            True if request is allowed, False if rate limited
        """
        now = datetime.utcnow()
        
        if webhook_id not in self._rate_limiters:
            self._rate_limiters[webhook_id] = {
                'window_start': now,
                'request_count': 0
            }
        
        limiter = self._rate_limiters[webhook_id]
        window_start = limiter['window_start']
        
        # Reset window if expired
        if (now - window_start).total_seconds() > window_seconds:
            limiter['window_start'] = now
            limiter['request_count'] = 0
        
        # Check limit
        if limiter['request_count'] >= max_requests:
            return False
        
        limiter['request_count'] += 1
        return True
    
    def _send_request(
        self,
        url: str,
        payload: dict,
        headers: dict,
        timeout: int = 10
    ) -> tuple[int, str, dict, int]:
        """
        Send HTTP POST request to webhook URL.
        
        Args:
            url: Webhook URL
            payload: Event payload
            headers: Request headers
            timeout: Request timeout in seconds
            
        Returns:
            Tuple of (status_code, response_body, response_headers, duration_ms)
        """
        start_time = time.time()
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
                allow_redirects=False
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return (
                response.status_code,
                response.text[:10000] if response.text else '',  # Limit response body
                dict(response.headers),
                duration_ms
            )
            
        except requests.exceptions.Timeout:
            duration_ms = int((time.time() - start_time) * 1000)
            raise WebhookTimeoutError(f"Request timed out after {timeout}s", duration_ms)
            
        except requests.exceptions.ConnectionError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            raise WebhookConnectionError(f"Connection error: {str(e)}", duration_ms)
            
        except requests.exceptions.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            raise WebhookRequestError(f"Request error: {str(e)}", duration_ms)
    
    def dispatch(
        self,
        event_type: str,
        payload: dict,
        context: Optional[dict] = None
    ) -> List[int]:
        """
        Dispatch an event to all subscribed webhooks.
        
        Args:
            event_type: Type of event (e.g., 'chat.message.created')
            payload: Event data
            context: Optional context (user_id, etc.)
            
        Returns:
            List of delivery IDs created
        """
        from app import db
        from app.models.webhook import Webhook, WebhookDelivery
        
        delivery_ids = []
        
        # Get all active webhooks subscribed to this event
        webhooks = Webhook.query.filter(
            Webhook.is_active == True
        ).all()
        
        # Filter webhooks that are subscribed to this event
        subscribed_webhooks = [
            w for w in webhooks 
            if event_type in (w.events or [])
        ]
        
        if not subscribed_webhooks:
            logger.debug(f"No webhooks subscribed to event: {event_type}")
            return delivery_ids
        
        # Build full event payload
        full_payload = {
            'event': event_type,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'data': payload
        }
        
        if context:
            full_payload['context'] = context
        
        for webhook in subscribed_webhooks:
            try:
                # Create delivery record
                delivery = WebhookDelivery(
                    webhook_id=webhook.id,
                    event_type=event_type,
                    payload=full_payload,
                    status=WebhookDelivery.STATUS_PENDING
                )
                db.session.add(delivery)
                db.session.flush()  # Get the ID
                
                webhook.total_deliveries += 1
                
                delivery_ids.append(delivery.id)
                
                # Dispatch asynchronously
                self._dispatch_async(webhook, delivery, full_payload)
                
            except Exception as e:
                logger.error(f"Error creating delivery for webhook {webhook.id}: {e}")
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing webhook deliveries: {e}")
        
        return delivery_ids
    
    def _dispatch_async(self, webhook, delivery, payload: dict):
        """Dispatch webhook in a background thread."""
        from flask import current_app
        
        # Get app context for background thread
        app = current_app._get_current_object()
        
        def run_dispatch():
            with app.app_context():
                self._execute_delivery(webhook.id, delivery.id, payload)
        
        thread = threading.Thread(target=run_dispatch, daemon=True)
        thread.start()
    
    def _execute_delivery(self, webhook_id: int, delivery_id: int, payload: dict):
        """Execute a single webhook delivery."""
        from app import db
        from app.models.webhook import Webhook, WebhookDelivery
        
        webhook = db.session.get(Webhook, webhook_id)
        delivery = db.session.get(WebhookDelivery, delivery_id)
        
        if not webhook or not delivery:
            return
        
        # Check rate limit
        if not self._check_rate_limit(webhook_id):
            delivery.mark_failed("Rate limit exceeded")
            db.session.commit()
            return
        
        # Build headers
        payload_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Prismateams-Webhook/1.0',
            'X-Webhook-Event': payload.get('event', ''),
            'X-Webhook-Delivery': str(delivery_id),
            'X-Webhook-Timestamp': payload.get('timestamp', ''),
        }
        
        # Add signature if secret is configured
        if webhook.secret:
            signature = self.generate_signature(payload_str, webhook.secret)
            headers['X-Webhook-Signature'] = f'sha256={signature}'
        
        # Add custom headers
        if webhook.headers:
            headers.update(webhook.headers)
        
        delivery.request_headers = headers
        
        try:
            status_code, response_body, response_headers, duration_ms = self._send_request(
                webhook.url,
                payload,
                headers,
                timeout=webhook.timeout or 10
            )
            
            # Check if successful (2xx status codes)
            if 200 <= status_code < 300:
                delivery.mark_success(
                    response_code=status_code,
                    response_body=response_body,
                    response_headers=response_headers,
                    duration_ms=duration_ms
                )
                logger.info(f"Webhook {webhook_id} delivered successfully: {status_code}")
            else:
                # Server returned an error
                self._handle_failure(
                    webhook, delivery,
                    f"Server returned {status_code}",
                    status_code, response_body
                )
                
        except WebhookTimeoutError as e:
            self._handle_failure(webhook, delivery, str(e))
            
        except WebhookConnectionError as e:
            self._handle_failure(webhook, delivery, str(e))
            
        except WebhookRequestError as e:
            self._handle_failure(webhook, delivery, str(e))
            
        except Exception as e:
            self._handle_failure(webhook, delivery, f"Unexpected error: {str(e)}")
            logger.exception(f"Unexpected error delivering webhook {webhook_id}")
        
        db.session.commit()
    
    def _handle_failure(
        self,
        webhook,
        delivery,
        error_message: str,
        response_code: Optional[int] = None,
        response_body: Optional[str] = None
    ):
        """Handle a failed delivery, potentially scheduling a retry."""
        max_retries = webhook.max_retries or 5
        retry_delay = webhook.retry_delay or 60
        
        if delivery.retry_count < max_retries:
            # Schedule retry with exponential backoff
            backoff = retry_delay * (2 ** delivery.retry_count)
            next_retry = datetime.utcnow() + timedelta(seconds=backoff)
            
            delivery.schedule_retry(next_retry)
            delivery.error_message = error_message
            delivery.response_code = response_code
            delivery.response_body = response_body
            
            logger.warning(
                f"Webhook {webhook.id} delivery {delivery.id} failed, "
                f"retry {delivery.retry_count}/{max_retries} scheduled for {next_retry}"
            )
            
            # Schedule the retry
            self._schedule_retry(webhook.id, delivery.id, backoff)
        else:
            # Max retries exceeded
            delivery.mark_failed(error_message, response_code, response_body)
            logger.error(
                f"Webhook {webhook.id} delivery {delivery.id} failed permanently "
                f"after {max_retries} retries: {error_message}"
            )
    
    def _schedule_retry(self, webhook_id: int, delivery_id: int, delay_seconds: int):
        """Schedule a retry after a delay."""
        from flask import current_app
        
        app = current_app._get_current_object()
        
        def retry():
            time.sleep(delay_seconds)
            with app.app_context():
                self._retry_delivery(webhook_id, delivery_id)
        
        thread = threading.Thread(target=retry, daemon=True)
        thread.start()
    
    def _retry_delivery(self, webhook_id: int, delivery_id: int):
        """Retry a failed delivery."""
        from app import db
        from app.models.webhook import Webhook, WebhookDelivery
        
        delivery = db.session.get(WebhookDelivery, delivery_id)
        
        if not delivery or delivery.status != WebhookDelivery.STATUS_RETRYING:
            return
        
        self._execute_delivery(webhook_id, delivery_id, delivery.payload)
    
    def send_test_event(self, webhook_id: int) -> dict:
        """
        Send a test event to a webhook.
        
        Args:
            webhook_id: Webhook ID
            
        Returns:
            Dictionary with test result
        """
        from app import db
        from app.models.webhook import Webhook
        
        webhook = db.session.get(Webhook, webhook_id)
        
        if not webhook:
            return {'success': False, 'error': 'Webhook nicht gefunden'}
        
        test_payload = {
            'event': 'test',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'data': {
                'message': 'Dies ist ein Test-Event von Prismateams',
                'webhook_name': webhook.name,
                'webhook_id': webhook.id
            }
        }
        
        payload_str = json.dumps(test_payload, separators=(',', ':'), ensure_ascii=False)
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Prismateams-Webhook/1.0',
            'X-Webhook-Event': 'test',
            'X-Webhook-Timestamp': test_payload['timestamp'],
        }
        
        if webhook.secret:
            signature = self.generate_signature(payload_str, webhook.secret)
            headers['X-Webhook-Signature'] = f'sha256={signature}'
        
        if webhook.headers:
            headers.update(webhook.headers)
        
        try:
            status_code, response_body, response_headers, duration_ms = self._send_request(
                webhook.url,
                test_payload,
                headers,
                timeout=webhook.timeout or 10
            )
            
            success = 200 <= status_code < 300
            
            return {
                'success': success,
                'status_code': status_code,
                'response_body': response_body[:500] if response_body else None,
                'duration_ms': duration_ms,
                'error': None if success else f"Server returned {status_code}"
            }
            
        except WebhookTimeoutError as e:
            return {'success': False, 'error': str(e), 'duration_ms': e.duration_ms}
            
        except WebhookConnectionError as e:
            return {'success': False, 'error': str(e), 'duration_ms': e.duration_ms}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


class WebhookError(Exception):
    """Base exception for webhook errors."""
    def __init__(self, message: str, duration_ms: int = 0):
        super().__init__(message)
        self.duration_ms = duration_ms


class WebhookTimeoutError(WebhookError):
    """Raised when webhook request times out."""
    pass


class WebhookConnectionError(WebhookError):
    """Raised when connection to webhook URL fails."""
    pass


class WebhookRequestError(WebhookError):
    """Raised for other request errors."""
    pass


# Global dispatcher instance
_dispatcher: Optional[WebhookDispatcher] = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    """Get the global webhook dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebhookDispatcher()
    return _dispatcher


def emit_webhook_event(event_type: str, payload: dict, context: Optional[dict] = None):
    """
    Convenience function to emit a webhook event.
    
    Args:
        event_type: Type of event (e.g., 'chat.message.created')
        payload: Event data
        context: Optional context (user_id, etc.)
    """
    try:
        dispatcher = get_webhook_dispatcher()
        dispatcher.dispatch(event_type, payload, context)
    except Exception as e:
        logger.error(f"Error emitting webhook event {event_type}: {e}")


def webhook_event(event_type: str):
    """
    Decorator to automatically emit webhook events after a function call.
    
    The decorated function should return a dict with the event payload,
    or a tuple of (result, payload) if the result should be returned.
    
    Example:
        @webhook_event('chat.message.created')
        def create_message(chat_id, content):
            message = ChatMessage(...)
            return {'message_id': message.id, 'chat_id': chat_id}
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            if result is None:
                return result
            
            # Handle tuple return (result, payload)
            if isinstance(result, tuple) and len(result) == 2:
                actual_result, payload = result
                emit_webhook_event(event_type, payload)
                return actual_result
            
            # Handle dict return (payload only)
            if isinstance(result, dict):
                emit_webhook_event(event_type, result)
            
            return result
        
        return wrapper
    return decorator
