package io.github.john9474.dizzybot.soundcloud;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.net.URI;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

class RefreshingPlaylistTest {
  private static AacPlaylist playlist(String signature, long length) {
    return new AacPlaylist(
        URI.create("https://cdn.example/init.mp4?Signature=" + signature),
        List.of(
            new AacPlaylist.Segment(
                URI.create("https://cdn.example/0.m4s?Signature=" + signature), 0)),
        length);
  }

  @Test
  void renewsSignedUrlsAfterTenMinutesAndPreservesTheTimeline() throws Exception {
    var now = new AtomicLong();
    var loads = new AtomicInteger();
    var original = playlist("original", 1000);
    var renewed = playlist("renewed", 1000);
    var state =
        new RefreshingPlaylist(() -> loads.incrementAndGet() == 1 ? original : renewed, now::get);
    assertSame(original, state.get());
    now.set(TimeUnit.MINUTES.toNanos(10) - 1);
    assertSame(original, state.get());
    assertEquals(1, loads.get());
    now.incrementAndGet();
    assertSame(renewed, state.get());
    assertEquals(2, loads.get());
    assertSame(renewed, state.get());
    assertEquals(2, loads.get());
  }

  @Test
  void refusesToContinueWithADifferentTimeline() throws Exception {
    var now = new AtomicLong();
    var state =
        new RefreshingPlaylist(() -> playlist("signature", now.get() == 0 ? 1000 : 2000), now::get);
    state.get();
    now.set(TimeUnit.MINUTES.toNanos(10));
    assertThrows(IOException.class, state::get);
  }
}
