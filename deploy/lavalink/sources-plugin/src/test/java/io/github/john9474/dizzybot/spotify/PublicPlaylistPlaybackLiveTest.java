package io.github.john9474.dizzybot.spotify;

import static org.junit.jupiter.api.Assertions.*;

import com.github.topi314.lavasrc.ytdlp.YtdlpAudioSourceManager;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayer;
import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.event.AudioEventAdapter;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.tools.io.MessageInput;
import com.sedmelluq.discord.lavaplayer.tools.io.MessageOutput;
import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

@EnabledIfSystemProperty(named = "dizzybot.spotifyPlaybackLive", matches = "true")
class PublicPlaylistPlaybackLiveTest {
  @Test
  void playsAnEncodedPublicPlaylistTrackThroughTheExistingMirror() throws Exception {
    var manager = new DefaultAudioPlayerManager();
    var source = new SpotifySource(new String[] {"ytsearch:%QUERY%"}, "", "", "GB");
    source.configure(manager);
    manager.registerSourceManager(source);
    manager.registerSourceManager(
        new YtdlpAudioSourceManager(
            System.getProperty("dizzybot.ytdlpPath", "/usr/local/bin/yt-dlp")));
    var failure = new AtomicReference<Throwable>();
    var player = manager.createPlayer();
    player.addListener(
        new AudioEventAdapter() {
          @Override
          public void onTrackException(
              AudioPlayer ignored, AudioTrack track, FriendlyException error) {
            failure.set(error);
          }
        });
    try {
      var playlist = (AudioPlaylist) source.loadPublicPlaylist("1fhVgfFO3TfNtRSf9dd7gM");
      var track = playlist.getTracks().get(0);
      var bytes = new ByteArrayOutputStream();
      manager.encodeTrack(new MessageOutput(bytes), track);
      var decoded =
          manager.decodeTrack(new MessageInput(new ByteArrayInputStream(bytes.toByteArray())))
              .decodedTrack;
      assertEquals(track.getInfo().title, decoded.getInfo().title);
      player.playTrack(decoded.makeClone());
      assertTimeoutPreemptively(
          Duration.ofSeconds(60),
          () -> {
            int received = 0;
            while (received < 100) {
              if (failure.get() != null)
                throw new AssertionError("Spotify mirroring failed", failure.get());
              var frame = player.provide();
              if (frame == null) Thread.sleep(5);
              else if (!frame.isTerminator()) {
                assertTrue(frame.getDataLength() > 0);
                received++;
              }
            }
          });
      System.out.println("Decoded and played public Spotify track: " + track.getInfo().title);
    } finally {
      player.destroy();
      manager.shutdown();
    }
  }
}
