/**
 * ESM bootstrap: exposes client download API on window for media_downloader.js (IIFE).
 */
const assetV = (typeof window !== 'undefined' && window.__mediaDlAssetV) || '';
const clientUrl = new URL(
    `./media_downloader_client.module.js${assetV ? `?v=${encodeURIComponent(assetV)}` : ''}`,
    import.meta.url,
).href;

try {
    const {
        configure,
        resolveVideoId,
        resolvePlaylistId,
        isPlaylistUrl,
        canonicalizePlaylistUrl,
        getVideoMetadata,
        downloadMedia,
        getPlaylistEntries,
        mapClientError,
        ClientDownloadError,
        signInToYoutube,
        signOutFromYoutube,
        isYoutubeSignedIn,
        cancelYoutubeSignIn,
        warmupYoutubeSession,
    } = await import(/* webpackIgnore: true */ clientUrl);

    window.MediaDownloaderClient = {
        configure,
        resolveVideoId,
        resolvePlaylistId,
        isPlaylistUrl,
        canonicalizePlaylistUrl,
        getVideoMetadata,
        downloadMedia,
        getPlaylistEntries,
        mapClientError,
        ClientDownloadError,
        signInToYoutube,
        signOutFromYoutube,
        isYoutubeSignedIn,
        cancelYoutubeSignIn,
        warmupYoutubeSession,
    };

    window.dispatchEvent(new CustomEvent('media-downloader-client-ready'));
} catch (err) {
    console.error('[MediaDownloader] Client bootstrap failed:', err);
    window.dispatchEvent(new CustomEvent('media-downloader-client-error', { detail: err }));
}
