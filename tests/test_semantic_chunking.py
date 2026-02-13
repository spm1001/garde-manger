"""Tests for semantic chunking (topic-boundary-aware splitting)."""

from datetime import datetime, timedelta
import pytest

from garde.llm import (
    MessageData,
    detect_topic_boundaries,
    split_semantic,
    DEFAULT_SEMANTIC_MIN,
    DEFAULT_SEMANTIC_MAX,
    DEFAULT_SEMANTIC_TARGET,
)


class TestMessageData:
    """Test MessageData dataclass."""

    def test_fields(self):
        """MessageData has all required fields."""
        ts = datetime(2024, 1, 1, 10, 0, 0)
        msg = MessageData(
            timestamp=ts,
            role='user',
            char_offset=0,
            char_length=100,
            is_tool_result=False,
            has_tool_use=True,
        )
        assert msg.timestamp == ts
        assert msg.role == 'user'
        assert msg.char_offset == 0
        assert msg.char_length == 100
        assert msg.is_tool_result is False
        assert msg.has_tool_use is True

    def test_defaults(self):
        """Default values for optional fields."""
        ts = datetime(2024, 1, 1, 10, 0, 0)
        msg = MessageData(
            timestamp=ts,
            role='assistant',
            char_offset=50,
            char_length=200,
        )
        assert msg.is_tool_result is False
        assert msg.has_tool_use is False


class TestDetectTopicBoundaries:
    """Test topic boundary detection."""

    def test_timestamp_gap_creates_boundary(self):
        """10-minute gap creates a boundary."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        t2 = t1 + timedelta(minutes=1)
        t3 = t2 + timedelta(minutes=10)  # 10 min gap

        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=10),
            MessageData(timestamp=t2, role='assistant', char_offset=12, char_length=20),
            MessageData(timestamp=t3, role='user', char_offset=34, char_length=15),
        ]
        content = 'x' * 50

        boundaries = detect_topic_boundaries(messages, content)
        assert boundaries == [2], "Should have boundary at index 2 (before 3rd message)"

    def test_user_after_assistant_run(self):
        """User message after 3+ assistant messages creates boundary."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=10),
            MessageData(timestamp=t1 + timedelta(seconds=30), role='assistant', char_offset=12, char_length=20),
            MessageData(timestamp=t1 + timedelta(seconds=60), role='assistant', char_offset=34, char_length=20),
            MessageData(timestamp=t1 + timedelta(seconds=90), role='assistant', char_offset=56, char_length=20),
            MessageData(timestamp=t1 + timedelta(seconds=120), role='user', char_offset=78, char_length=15),
        ]
        content = 'x' * 100

        boundaries = detect_topic_boundaries(messages, content)
        assert boundaries == [4], "Should have boundary at index 4 (user after 3 assistants)"

    def test_no_boundaries_in_short_conversation(self):
        """Short conversations with no signals have no boundaries."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=10),
            MessageData(timestamp=t1 + timedelta(seconds=30), role='assistant', char_offset=12, char_length=20),
        ]
        content = 'x' * 35

        boundaries = detect_topic_boundaries(messages, content)
        assert boundaries == []

    def test_single_message_no_boundaries(self):
        """Single message cannot have boundaries."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=10),
        ]
        content = 'x' * 10

        boundaries = detect_topic_boundaries(messages, content)
        assert boundaries == []

    def test_empty_messages(self):
        """Empty message list has no boundaries."""
        boundaries = detect_topic_boundaries([], "")
        assert boundaries == []

    def test_explicit_marker_adds_weight(self):
        """Explicit markers like 'let's move on' add weight."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        # Create content with marker
        content = "First part\n\nLet's move on to the next topic\n\nThird part"
        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=10),
            MessageData(timestamp=t1 + timedelta(minutes=3), role='assistant', char_offset=12, char_length=35),
            MessageData(timestamp=t1 + timedelta(minutes=4), role='user', char_offset=49, char_length=10),
        ]

        boundaries = detect_topic_boundaries(messages, content)
        # The 3-min gap (< 5min threshold) alone wouldn't trigger,
        # but combined with marker weight it might
        # Actually, 3 min is 180 seconds which is < 300, so no timestamp signal
        # and marker gives 0.2 weight, which is < 0.5 threshold
        # So no boundary expected in this case
        assert boundaries == []


class TestSplitSemantic:
    """Test semantic chunk assembly."""

    def test_small_content_single_chunk(self):
        """Content smaller than max stays as single chunk."""
        content = 'A' * 50000
        messages = [
            MessageData(
                timestamp=datetime(2024, 1, 1, 10, 0, 0),
                role='user',
                char_offset=0,
                char_length=50000
            ),
        ]

        chunks = split_semantic(content, messages)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_merge_small_segments(self):
        """Segments smaller than min get merged together."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)

        # Create 3 small segments (5K each) with 10-min gaps
        seg1 = 'A' * 5000
        seg2 = 'B' * 5000
        seg3 = 'C' * 5000
        content = seg1 + '\n\n' + seg2 + '\n\n' + seg3

        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=5000),
            MessageData(timestamp=t1 + timedelta(minutes=10), role='user', char_offset=5002, char_length=5000),
            MessageData(timestamp=t1 + timedelta(minutes=20), role='user', char_offset=10004, char_length=5000),
        ]

        # With min=16K (> combined 15K of segments), all should merge to 1 chunk
        chunks = split_semantic(content, messages, min_size=16000)
        assert len(chunks) == 1
        assert len(chunks[0]) == len(content)

    def test_partial_merge_small_segments(self):
        """Some segments merge, others stay separate based on min threshold."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)

        # Create 3 segments (5K each) with 10-min gaps
        seg1 = 'A' * 5000
        seg2 = 'B' * 5000
        seg3 = 'C' * 5000
        content = seg1 + '\n\n' + seg2 + '\n\n' + seg3

        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=5000),
            MessageData(timestamp=t1 + timedelta(minutes=10), role='user', char_offset=5002, char_length=5000),
            MessageData(timestamp=t1 + timedelta(minutes=20), role='user', char_offset=10004, char_length=5000),
        ]

        # With min=10K, first gets pushed (5K), then two remain undersized
        # Final re-merge combines the last undersized chunk
        chunks = split_semantic(content, messages, min_size=10000)
        assert len(chunks) == 2  # First chunk too small, gets one merged later

    def test_preserve_large_segments(self):
        """Segments larger than min are preserved as separate chunks."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)

        # Create 3 large segments (20K each) with 10-min gaps
        seg1 = 'A' * 20000
        seg2 = 'B' * 25000
        seg3 = 'C' * 18000
        content = seg1 + '\n\n' + seg2 + '\n\n' + seg3

        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=20000),
            MessageData(timestamp=t1 + timedelta(minutes=10), role='user', char_offset=20002, char_length=25000),
            MessageData(timestamp=t1 + timedelta(minutes=20), role='user', char_offset=45004, char_length=18000),
        ]

        chunks = split_semantic(content, messages, min_size=15000)
        assert len(chunks) == 3
        assert 'A' * 100 in chunks[0]
        assert 'B' * 100 in chunks[1]
        assert 'C' * 100 in chunks[2]

    def test_split_oversized_chunks(self):
        """Chunks larger than max get split at paragraph breaks."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)

        # Create content > max (120K with max=80K)
        seg = ('X' * 40000) + '\n\n' + ('Y' * 40000) + '\n\n' + ('Z' * 40000)
        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=len(seg)),
        ]

        chunks = split_semantic(seg, messages, max_size=80000, target_size=40000)
        # Should be split into multiple chunks
        assert len(chunks) >= 2
        total = sum(len(c) for c in chunks)
        # Total should be close to original (minus some stripped whitespace)
        assert total >= len(seg) - 10

    def test_no_messages_falls_back(self):
        """Without messages, falls back to paragraph-based splitting."""
        content = ('A' * 50000) + '\n\n' + ('B' * 50000)
        chunks = split_semantic(content, [], max_size=80000)
        assert len(chunks) >= 1

    def test_no_boundaries_single_chunk(self):
        """Content with no detected boundaries stays as one chunk."""
        t1 = datetime(2024, 1, 1, 10, 0, 0)
        content = 'A' * 50000

        messages = [
            MessageData(timestamp=t1, role='user', char_offset=0, char_length=25000),
            MessageData(timestamp=t1 + timedelta(seconds=30), role='assistant', char_offset=25002, char_length=24998),
        ]

        chunks = split_semantic(content, messages)
        assert len(chunks) == 1


class TestDefaultConstants:
    """Test semantic chunking default values."""

    def test_semantic_min(self):
        """Default semantic min is 15K."""
        assert DEFAULT_SEMANTIC_MIN == 15_000

    def test_semantic_max(self):
        """Default semantic max is 80K."""
        assert DEFAULT_SEMANTIC_MAX == 80_000

    def test_semantic_target(self):
        """Default semantic target is 40K."""
        assert DEFAULT_SEMANTIC_TARGET == 40_000
