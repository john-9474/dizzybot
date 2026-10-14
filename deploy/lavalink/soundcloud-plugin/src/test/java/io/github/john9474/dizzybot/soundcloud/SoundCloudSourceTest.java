package io.github.john9474.dizzybot.soundcloud;

import static org.junit.jupiter.api.Assertions.*;

import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.source.soundcloud.*;
import com.sedmelluq.discord.lavaplayer.tools.io.MessageInput;
import com.sedmelluq.discord.lavaplayer.tools.io.MessageOutput;
import com.sedmelluq.discord.lavaplayer.track.*;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.http.client.methods.HttpGet;
import org.junit.jupiter.api.Test;

class SoundCloudSourceTest {
  static AudioTrackInfo info(String identifier) {
    return new AudioTrackInfo(
        "Song", "Artist", 120_000, identifier, false, "https://soundcloud.com/artist/song");
  }

  @Test
  void selectsAacAndKeepsLegacyFormats() {
    var formats = new AacFormatHandler();
    var mp3 =
        new DefaultSoundCloudTrackFormat(
            "id", "hls", "audio/mpeg", "https://api-v2.soundcloud.com/mp3");
    var opus =
        new DefaultSoundCloudTrackFormat(
            "id", "hls", "audio/ogg", "https://api-v2.soundcloud.com/opus");
    var aac =
        new DefaultSoundCloudTrackFormat(
            "id", "hls", "audio/mp4; codecs=\"mp4a.40.2\"", "https://api-v2.soundcloud.com/aac");
    assertSame(aac, formats.chooseBestFormat(List.of(mp3, opus, aac)));
    assertEquals("A:" + aac.getLookupUrl(), formats.buildFormatIdentifier(aac));
    assertSame(opus, formats.chooseBestFormat(List.of(mp3, opus)));
    assertTrue(formats.buildFormatIdentifier(opus).startsWith("O:"));
    assertTrue(formats.buildFormatIdentifier(mp3).startsWith("U:"));
    var adaptive =
        new DefaultSoundCloudTrackFormat(
            "id", "hls", "audio/mpegurl", "https://example.com/adaptive");
    assertThrows(RuntimeException.class, () -> formats.chooseBestFormat(List.of(adaptive)));
  }

  @Test
  void adaptsSearchAndSetTracksAndPreservesSelection() {
    var source = new SoundCloudSource(true, true);
    try {
      AudioTrack aac =
          new SoundCloudAudioTrack(info("A:https://api-v2.soundcloud.com/aac"), source);
      AudioTrack mp3 =
          new SoundCloudAudioTrack(info("U:https://api-v2.soundcloud.com/mp3"), source);
      assertInstanceOf(SoundCloudAacTrack.class, source.adaptItem(aac));
      assertSame(mp3, source.adaptItem(mp3));
      for (boolean search : List.of(true, false)) {
        var original = new BasicAudioPlaylist("Set", List.of(mp3, aac), aac, search);
        var adapted = (AudioPlaylist) source.adaptItem(original);
        assertEquals("Set", adapted.getName());
        assertEquals(search, adapted.isSearchResult());
        assertSame(mp3, adapted.getTracks().get(0));
        assertInstanceOf(SoundCloudAacTrack.class, adapted.getTracks().get(1));
        assertSame(adapted.getTracks().get(1), adapted.getSelectedTrack());
        var unselected =
            (AudioPlaylist)
                source.adaptItem(new BasicAudioPlaylist("Set", List.of(aac), null, search));
        assertNull(unselected.getSelectedTrack());
      }
    } finally {
      source.shutdown();
    }
  }

  @Test
  void roundTripsEncodedTracksAndClonesWithoutChangingSourceOrMetadata() throws Exception {
    var manager = new DefaultAudioPlayerManager();
    var source = new SoundCloudSource(true, true);
    manager.registerSourceManager(source);
    try {
      var track =
          (AudioTrack)
              source.adaptItem(
                  new SoundCloudAudioTrack(info("A:https://api-v2.soundcloud.com/aac"), source));
      var bytes = new ByteArrayOutputStream();
      manager.encodeTrack(new MessageOutput(bytes), track);
      var decoded =
          manager.decodeTrack(new MessageInput(new ByteArrayInputStream(bytes.toByteArray())))
              .decodedTrack;
      assertInstanceOf(SoundCloudAacTrack.class, decoded);
      assertEquals(track.getIdentifier(), decoded.getIdentifier());
      assertEquals(track.getInfo().title, decoded.getInfo().title);
      assertEquals(track.getInfo().uri, decoded.getInfo().uri);
      assertEquals("soundcloud", decoded.getSourceManager().getSourceName());
      assertInstanceOf(SoundCloudAacTrack.class, decoded.makeClone());
    } finally {
      manager.shutdown();
    }
  }

  @Test
  void leavesSignedCdnRequestUntouched() throws Exception {
    var received = new AtomicReference<String>();
    var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext(
        "/media",
        exchange -> {
          received.set(exchange.getRequestURI().toASCIIString());
          exchange.sendResponseHeaders(200, 1);
          exchange.getResponseBody().write(0);
          exchange.close();
        });
    server.start();
    var source = new SoundCloudSource(true, true);
    String path = "/media?Policy=a%2Fb~c&Signature=d%2Be_";
    try (var http = source.getMediaInterface();
        var response =
            http.execute(new HttpGet("http://127.0.0.1:" + server.getAddress().getPort() + path))) {
      assertEquals(200, response.getStatusLine().getStatusCode());
      assertEquals(path, received.get());
    } finally {
      source.shutdown();
      server.stop(0);
    }
  }
}
