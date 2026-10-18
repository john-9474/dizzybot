package io.github.john9474.dizzybot.spotify;

import static org.junit.jupiter.api.Assertions.*;

import com.github.topi314.lavasrc.spotify.SpotifyAudioTrack;
import com.sedmelluq.discord.lavaplayer.tools.JsonBrowser;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class PublicPlaylistLoaderTest {
  static final String ID = "1fhVgfFO3TfNtRSf9dd7gM";
  static final String EMBED =
      "<script id=\"__NEXT_DATA__\" type=\"application/json\">"
          + "{\"props\":{\"pageProps\":{\"state\":{\"settings\":{\"session\":{\"accessToken\":\"test-public-session\"}}}}}}"
          + "</script>";

  static String track(String title) {
    return "{\"itemV2\":{\"data\":{\"__typename\":\"Track\",\"uri\":\"spotify:track:30VrBsh1STRBoIrhQOAwzK\","
               + "\"name\":\""
        + title
        + "\",\"trackDuration\":{\"totalMilliseconds\":238573},"
        + "\"artists\":{\"items\":[{\"profile\":{\"name\":\"Example artist\"}}]}}}}";
  }

  static JsonBrowser page(int total, List<String> items) throws IOException {
    return JsonBrowser.parse(
        "{\"data\":{\"playlistV2\":{\"__typename\":\"Playlist\","
            + "\"uri\":\"spotify:playlist:"
            + ID
            + "\",\"name\":\"Public playlist\","
            + "\"content\":{\"totalCount\":"
            + total
            + ",\"items\":["
            + String.join(",", items)
            + "]}}}}");
  }

  static class FakeTransport implements PublicPlaylistLoader.Transport {
    final List<JsonBrowser> pages = new ArrayList<>();
    final List<JsonBrowser> requests = new ArrayList<>();

    @Override
    public String embed(String id) {
      assertEquals(ID, id);
      return EMBED;
    }

    @Override
    public JsonBrowser page(String token, String payload) throws IOException {
      assertEquals("test-public-session", token);
      requests.add(JsonBrowser.parse(payload));
      return pages.remove(0);
    }
  }

  @Test
  void paginatesPastOneHundredAndPreservesOrderAndDuplicates() throws Exception {
    var transport = new FakeTransport();
    var first = new ArrayList<String>();
    for (int i = 0; i < 100; i++) first.add(track("Track " + i));
    transport.pages.add(page(103, first));
    transport.pages.add(
        page(103, List.of(track("Track 100"), track("Track 100"), track("Track 102"))));
    var source = new SpotifySource(new String[] {"scsearch:%QUERY%"}, "", "", "GB");
    try {
      var playlist = new PublicPlaylistLoader(transport).load(ID, source, 500);
      assertEquals(103, playlist.getTracks().size());
      assertEquals("Track 99", playlist.getTracks().get(99).getInfo().title);
      assertEquals("Track 100", playlist.getTracks().get(100).getInfo().title);
      assertEquals("Track 100", playlist.getTracks().get(101).getInfo().title);
      assertInstanceOf(SpotifyAudioTrack.class, playlist.getTracks().get(102));
      assertEquals(238573, playlist.getTracks().get(102).getDuration());
      assertEquals("spotify", playlist.getTracks().get(102).getSourceManager().getSourceName());
      assertEquals(100, transport.requests.get(1).get("variables").get("offset").asLong(-1));
    } finally {
      source.shutdown();
    }
  }

  @Test
  void respectsConfiguredLimitWithoutRequestingExtraPages() throws Exception {
    var transport = new FakeTransport();
    transport.pages.add(page(198, List.of(track("One"), track("Two"))));
    assertEquals(2, new PublicPlaylistLoader(transport).load(ID, null, 2).getTracks().size());
    assertEquals(2, transport.requests.get(0).get("variables").get("limit").asLong(-1));
    assertEquals(1, transport.requests.size());
  }

  @Test
  void rejectsIncompletePagesInsteadOfReportingSuccess() throws Exception {
    var transport = new FakeTransport();
    transport.pages.add(page(198, List.of(track("One"))));
    transport.pages.add(page(198, List.of()));
    assertThrows(IOException.class, () -> new PublicPlaylistLoader(transport).load(ID, null, 500));
  }

  @Test
  void rejectsChangedTotalsDuringPagination() throws Exception {
    var transport = new FakeTransport();
    transport.pages.add(page(198, List.of(track("One"))));
    transport.pages.add(page(199, List.of(track("Two"))));
    assertThrows(IOException.class, () -> new PublicPlaylistLoader(transport).load(ID, null, 500));
  }

  @Test
  void rejectsAChangedRevisionEvenWhenTheItemCountMatches() throws Exception {
    var transport = new FakeTransport();
    transport.pages.add(
        JsonBrowser.parse(
            page(2, List.of(track("One")))
                .format()
                .replace("\"content\"", "\"revisionId\":\"before\",\"content\"")));
    transport.pages.add(
        JsonBrowser.parse(
            page(2, List.of(track("Two")))
                .format()
                .replace("\"content\"", "\"revisionId\":\"after\",\"content\"")));
    assertThrows(IOException.class, () -> new PublicPlaylistLoader(transport).load(ID, null, 500));
  }

  @Test
  void skipsEpisodesAndUnavailableItemsWithoutUsingPreviewAudio() throws Exception {
    var transport = new FakeTransport();
    transport.pages.add(
        page(
            3,
            List.of(
                "{\"itemV2\":{\"data\":{\"__typename\":\"Episode\"}}}",
                "{\"itemV2\":{\"data\":{\"__typename\":\"NotFound\"}}}",
                track("One"))));
    var playlist = new PublicPlaylistLoader(transport).load(ID, null, 500);
    assertEquals(1, playlist.getTracks().size());
    assertEquals(
        "https://open.spotify.com/track/30VrBsh1STRBoIrhQOAwzK",
        playlist.getTracks().get(0).getInfo().uri);
  }

  @Test
  void rejectsMissingSessionInvalidIdsAndGraphqlErrors() throws Exception {
    assertThrows(IOException.class, () -> PublicPlaylistLoader.tokenFromEmbed("<html></html>"));
    var transport = new FakeTransport();
    assertThrows(
        IOException.class, () -> new PublicPlaylistLoader(transport).load("../bad", null, 500));
    transport.pages.add(JsonBrowser.parse("{\"errors\":[{\"message\":\"NotFound\"}]}"));
    assertThrows(IOException.class, () -> new PublicPlaylistLoader(transport).load(ID, null, 500));
  }

  @Test
  void onlyFallsBackForAccessDenials() {
    assertTrue(
        SpotifySource.isAccessDenied(
            new RuntimeException(
                new IllegalStateException("Response code from channel info is 401"))));
    assertTrue(
        SpotifySource.isAccessDenied(
            new IllegalStateException("Response code from channel info is 403")));
    assertFalse(
        SpotifySource.isAccessDenied(
            new IllegalStateException("Response code from channel info is 429")));
    assertFalse(SpotifySource.isAccessDenied(new IOException("Connection timed out")));
  }
}
