package io.github.john9474.dizzybot.spotify;

import static org.junit.jupiter.api.Assertions.*;

import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

@EnabledIfSystemProperty(named = "dizzybot.spotifyLive", matches = "true")
class PublicPlaylistLiveTest {
  @Test
  void retrievesBothPagesOfPublicPlaylistWithoutAccountCredentials() throws Exception {
    var source = new SpotifySource(new String[] {"scsearch:%QUERY%"}, "", "", "GB");
    try {
      var playlist =
          assertInstanceOf(
              AudioPlaylist.class, source.loadPublicPlaylist("1fhVgfFO3TfNtRSf9dd7gM"));
      assertEquals("classic bangers x", playlist.getName());
      assertTrue(playlist.getTracks().size() > 100);
      assertEquals("Disturbia", playlist.getTracks().get(0).getInfo().title);
      System.out.println(
          "Public Spotify playlist imported " + playlist.getTracks().size() + " tracks");
    } finally {
      source.shutdown();
    }
  }
}
