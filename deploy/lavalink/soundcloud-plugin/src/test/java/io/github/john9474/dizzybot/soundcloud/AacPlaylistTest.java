package io.github.john9474.dizzybot.soundcloud;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.net.URI;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class AacPlaylistTest {
  private static final URI BASE =
      URI.create("https://playback.media-streaming.soundcloud.cloud/track/playlist.m3u8");

  private static String manifest(String extra) {
    return "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-MAP:URI=\"init.mp4?Signature=keep%2Bthis\"\n"
        + extra
        + "\n#EXTINF:10.007800,\nsegment0.m4s?Policy=original%2Fvalue\n"
        + "#EXTINF:9.984580,\nsegment1.m4s\n#EXTINF:1.000000,\nsegment2.m4s\n#EXT-X-ENDLIST";
  }

  @Test
  void keepsInitializationSignedUrlsAndCumulativeTimecodes() throws Exception {
    var playlist = AacPlaylist.parse(BASE, manifest("").split("\n"));
    assertEquals(
        "https://playback.media-streaming.soundcloud.cloud/track/init.mp4?Signature=keep%2Bthis",
        playlist.initialization().toASCIIString());
    assertEquals(
        "https://playback.media-streaming.soundcloud.cloud/track/segment0.m4s?Policy=original%2Fvalue",
        playlist.segments().get(0).uri().toASCIIString());
    assertEquals(10_008, playlist.segments().get(1).startMs());
    assertEquals(19_992, playlist.segments().get(2).startMs());
    assertEquals(20_992, playlist.durationMs());
    assertEquals(0, playlist.segmentAt(0));
    assertEquals(0, playlist.segmentAt(10_007));
    assertEquals(1, playlist.segmentAt(10_008));
    assertEquals(2, playlist.segmentAt(20_000));
    assertEquals(3, playlist.segmentAt(20_992));
  }

  @Test
  void renewsUrlsOnlyWhenTimelineMatches() throws Exception {
    var initial = AacPlaylist.parse(BASE, manifest("").split("\n"));
    var renewed = AacPlaylist.parse(BASE, manifest("").replace("original", "renewed").split("\n"));
    assertTrue(initial.sameTimeline(renewed));
    var changed = AacPlaylist.parse(BASE, manifest("").replace("9.984580", "9.900000").split("\n"));
    assertFalse(initial.sameTimeline(changed));
  }

  @ParameterizedTest
  @ValueSource(
      strings = {
        "#EXT-X-KEY:METHOD=AES-128,URI=\"key\"",
        "#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"key\"",
        "#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI=\"key\"",
        "#EXT-X-BYTERANGE:100@0",
        "#EXT-X-DISCONTINUITY",
        "#EXT-X-MAP:URI=\"other.mp4\"",
        "#EXT-X-MAP:URI=\"init.mp4\",BYTERANGE=\"100@0\""
      })
  void rejectsUnsupportedOrEncryptedPlaylists(String directive) {
    assertThrows(IOException.class, () -> AacPlaylist.parse(BASE, manifest(directive).split("\n")));
  }

  @Test
  void rejectsIncompleteOrMalformedMedia() {
    assertThrows(
        IOException.class,
        () -> AacPlaylist.parse(BASE, manifest("").replace("#EXT-X-ENDLIST", "").split("\n")));
    assertThrows(
        IOException.class,
        () -> AacPlaylist.parse(BASE, manifest("").replace("10.007800", "NaN").split("\n")));
    assertThrows(
        IOException.class,
        () ->
            AacPlaylist.parse(
                BASE, manifest("").replace("segment1.m4s", "file:///etc/passwd").split("\n")));
    assertThrows(
        IOException.class,
        () ->
            AacPlaylist.parse(
                BASE,
                new String[] {"#EXTM3U", "#EXT-X-STREAM-INF:BANDWIDTH=160000", "variant.m3u8"}));
  }
}
