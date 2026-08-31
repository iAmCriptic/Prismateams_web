/**
 * ESM bootstrap: exposes client download API on window for media_downloader.js (IIFE).
 */
import {
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
} from './media_downloader_client.module.js';

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
};
