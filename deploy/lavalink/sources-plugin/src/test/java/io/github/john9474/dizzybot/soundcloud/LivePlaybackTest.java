package io.github.john9474.dizzybot.soundcloud;

import static org.junit.jupiter.api.Assertions.*;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayer;
import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.event.AudioEventAdapter;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.AudioReference;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/** Optional: consumes Opus frames in memory, without Discord credentials or saving audio. */
@EnabledIfSystemProperty(named = "dizzybot.live", matches = "true")
class LivePlaybackTest {
  @Test
  void playsAndSeeksRealSoundCloudAacTrack() throws Exception {
    var manager = new DefaultAudioPlayerManager();
    var source = new SoundCloudSource(true, true);
    manager.registerSourceManager(source);
    manager.setUseSeekGhosting(false);
    var failure = new AtomicReference<Throwable>();
    AudioPlayer player = manager.createPlayer();
    player.addListener(
        new AudioEventAdapter() {
          @Override
          public void onTrackException(
              AudioPlayer ignored, AudioTrack track, FriendlyException error) {
            failure.set(error);
          }
        });
    try {
      String url =
          System.getProperty("dizzybot.liveUrl", "https://soundcloud.com/mtrn/chavvy-wobblaz");
      var loaded = manager.loadItemSync(new AudioReference(url, null));
      assertInstanceOf(SoundCloudAacTrack.class, loaded);
      AudioTrack track = (AudioTrack) loaded;
      assertTrue(track.getDuration() > 90_000);
      // Exercise the same source decoding used by Lavalink's encoded-track API.
      track = source.decodeTrack(track.getInfo(), null);
      player.playTrack(track);
      consumeFrames(player, failure, 650, 0); // Cross the first ten-second segment boundary.
      track.setPosition(65_000);
      consumeFrames(player, failure, 120, 65_000);
      track.setPosition(15_000);
      consumeFrames(player, failure, 120, 15_000);
      track.setPosition(track.getDuration() - 1500);
      consumeFrames(player, failure, 20, track.getDuration() - 1500);
      assertTimeoutPreemptively(
          Duration.ofSeconds(15),
          () -> {
            while (player.getPlayingTrack() != null) {
              assertNull(failure.get());
              player.provide();
              Thread.sleep(5);
            }
          });
      player.setVolume(70);
      player.playTrack(track.makeClone());
      consumeFrames(player, failure, 50, 0);
      assertNull(failure.get());
    } finally {
      player.destroy();
      manager.shutdown();
    }
  }

  private static void consumeFrames(
      AudioPlayer player, AtomicReference<Throwable> failure, int count, long minimumTimecode) {
    assertTimeoutPreemptively(
        Duration.ofSeconds(45),
        () -> {
          int received = 0;
          while (received < count) {
            if (failure.get() != null) {
              throw new AssertionError("SoundCloud playback failed", failure.get());
            }
            var frame = player.provide();
            if (frame == null) {
              Thread.sleep(5);
            } else if (!frame.isTerminator()) {
              assertTrue(
                  frame.getTimecode() >= minimumTimecode,
                  () ->
                      "Expected time >= " + minimumTimecode + ", received " + frame.getTimecode());
              assertTrue(frame.getDataLength() > 0);
              received++;
            }
          }
        });
  }
}
