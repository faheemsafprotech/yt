import { spawn } from 'child_process'
import fs from 'fs'
import path from 'path'
import os from 'os'
import archiver from 'archiver'
import { sanitizeFilename } from './utils'

export interface DownloadOptions {
  embedThumbnail?: boolean
  embedChapter?: boolean
  embedMetadata?: boolean
  embedSubtitle?: boolean
  isAudioOnly?: boolean
  subtitleLanguage?: string
  filename?: string
}

export interface DownloadStats {
  progress: number
  size: string
  speed: string
  eta: string
}

class DownloadService {
  private readonly tempDir: string

  constructor() {
    this.tempDir = path.join(os.tmpdir(), 'youtube-downloader')
    this.ensureTempDir()
  }

  private async ensureTempDir() {
    try {
      await fs.promises.mkdir(this.tempDir, { recursive: true })
    } catch (error) {
      console.error('Failed to create temp directory:', error)
      throw new Error('Failed to initialize download service')
    }
  }

  async downloadVideo(
    contentId: string,
    formatId: string,
    options: DownloadOptions,
    onProgress?: (chunk: string) => void,
    abortSignal?: AbortSignal,
  ): Promise<string> {
    const sanitizedFilename = sanitizeFilename(options.filename || contentId)

    const outputPath = path.join(this.tempDir, `${sanitizedFilename}.%(ext)s`)
    const args = this.buildYtDlpArgs(contentId, formatId, outputPath, options, false)

    return new Promise((resolve, reject) => {
      const ytdlp = spawn('yt-dlp', args)
      let stderrOutput = ''

      // Handle abort signal
      if (abortSignal) {
        abortSignal.addEventListener('abort', () => {
          console.log('Download cancelled, killing yt-dlp process')
          ytdlp.kill('SIGTERM')
          reject(new Error('Download cancelled'))
        })
      }

      ytdlp.stdout.on('data', (data) => {
        const output = data.toString()
        onProgress?.(output)
      })

      ytdlp.stderr.on('data', (data) => {
        stderrOutput += data.toString()
        console.error(`yt-dlp stderr: ${data}`)
      })

      ytdlp.on('close', async (code) => {
        if (code === 0) {
          try {
            const files = await fs.promises.readdir(this.tempDir)
            const downloadedFile = files.find((file) => file.startsWith(sanitizedFilename))
            if (downloadedFile) {
              resolve(path.join(this.tempDir, downloadedFile))
            } else {
              console.error('stderr on close (success):', stderrOutput)
              reject(new Error('Download completed but output file not found in temp directory.'))
            }
          } catch (error) {
            console.error('Error reading temp directory:', error)
            reject(error)
          }
        } else {
          console.error('stderr on close (error):', stderrOutput)
          reject(
            new Error(
              `Download failed. yt-dlp exited with code ${code}. Error: ${stderrOutput.split('\n').slice(-2).join(' ') || 'Unknown error'}`,
            ),
          )
        }
      })

      ytdlp.on('error', (err) => {
        console.error('Failed to start yt-dlp process:', err)
        reject(new Error(`Failed to start download process: ${err.message}`))
      })
    })
  }

  async downloadPlaylist(
    playlistId: string,
    formatId: string,
    options: DownloadOptions,
    selectedVideos: any[] = [],
    onProgress?: (chunk: string) => void,
    abortSignal?: AbortSignal,
  ): Promise<string> {
    const sanitizedPlaylistTitle = sanitizeFilename(options.filename || playlistId)

    const playlistSubDir = path.join(this.tempDir, `${sanitizedPlaylistTitle}_${Date.now()}`)
    await fs.promises.mkdir(playlistSubDir, { recursive: true })

    const zipFilePath = path.join(this.tempDir, `${sanitizedPlaylistTitle}.zip`)

    if (selectedVideos && selectedVideos.length > 0) {
      return this.downloadSelectedVideos(selectedVideos, formatId, options, playlistSubDir, zipFilePath, onProgress, abortSignal)
    }

    const outputPathTemplate = path.join(playlistSubDir, `%(playlist_index)s - %(title)s.%(ext)s`)
    const args = this.buildYtDlpArgs(playlistId, formatId, outputPathTemplate, options, true)

    return new Promise((resolve, reject) => {
      const ytdlp = spawn('yt-dlp', args)
      let stderrOutput = ''

      // Handle abort signal
      if (abortSignal) {
        abortSignal.addEventListener('abort', () => {
          console.log('Playlist download cancelled, killing yt-dlp process')
          ytdlp.kill('SIGTERM')
          reject(new Error('Download cancelled'))
        })
      }

      ytdlp.stdout.on('data', (data) => {
        const output = data.toString()
        onProgress?.(output)
      })

      ytdlp.stderr.on('data', (data) => {
        stderrOutput += data.toString()
        console.error(`yt-dlp stderr: ${data}`)
      })

      ytdlp.on('close', async (code) => {
        if (code === 0) {
          onProgress?.('data: Zipping files...\n\n')
          try {
            const outputZip = fs.createWriteStream(zipFilePath)
            const archive = archiver('zip', {
              zlib: { level: 9 },
            })

            outputZip.on('close', () => {
              onProgress?.('data: Zipping complete.\n\n')

              fs.promises
                .rm(playlistSubDir, { recursive: true, force: true })
                .then(() => console.log(`Cleaned up ${playlistSubDir}`))
                .catch((err) => console.error(`Failed to clean up ${playlistSubDir}:`, err))
              resolve(zipFilePath)
            })

            archive.on('warning', (err) => {
              if (err.code === 'ENOENT') {
                console.warn('Archiver warning:', err)
              } else {
                reject(err)
              }
            })

            archive.on('error', (err) => {
              reject(err)
            })

            archive.pipe(outputZip)
            archive.directory(playlistSubDir, false)
            await archive.finalize()
          } catch (zipError) {
            console.error('Error during zipping:', zipError)
            reject(
              new Error(
                `Download successful, but failed to zip files: ${zipError instanceof Error ? zipError.message : zipError}`,
              ),
            )

            fs.promises
              .rm(playlistSubDir, { recursive: true, force: true })
              .catch((err) => console.error(`Failed cleanup after zip error for ${playlistSubDir}:`, err))
          }
        } else {
          console.error('stderr on close (error):', stderrOutput)

          fs.promises
            .rm(playlistSubDir, { recursive: true, force: true })
            .catch((err) => console.error(`Failed cleanup after download error for ${playlistSubDir}:`, err))
          reject(
            new Error(
              `Playlist download failed. yt-dlp exited with code ${code}. Error: ${stderrOutput.split('\n').slice(-2).join(' ') || 'Unknown error'}`,
            ),
          )
        }
      })

      ytdlp.on('error', (err) => {
        console.error('Failed to start yt-dlp process:', err)

        fs.promises
          .rm(playlistSubDir, { recursive: true, force: true })
          .catch((cleanupErr) =>
            console.error(`Failed cleanup after process start error for ${playlistSubDir}:`, cleanupErr),
          )
        reject(new Error(`Failed to start download process: ${err.message}`))
      })
    })
  }

  private async downloadSelectedVideos(
    selectedVideos: any[],
    formatId: string,
    options: DownloadOptions,
    playlistSubDir: string,
    zipFilePath: string,
    onProgress?: (chunk: string) => void,
    abortSignal?: AbortSignal,
  ): Promise<string> {
    return new Promise(async (resolve, reject) => {
      try {
        let completedVideos = 0
        const totalVideos = selectedVideos.length
        const processes: any[] = []

        for (const video of selectedVideos) {
          const videoId = video.id
          const videoTitle = sanitizeFilename(video.title || videoId)
          const outputPath = path.join(playlistSubDir, `${video.index || completedVideos + 1} - ${videoTitle}.%(ext)s`)
          
          onProgress?.(`data: Downloading ${completedVideos + 1}/${totalVideos}: ${video.title}\n\n`)

          const args = this.buildYtDlpArgs(videoId, formatId, outputPath, options, false)

          await new Promise<void>((resolveVideo, rejectVideo) => {
            const ytdlp = spawn('yt-dlp', args)
            processes.push(ytdlp)
            let stderrOutput = ''

            // Handle abort signal
            if (abortSignal) {
              abortSignal.addEventListener('abort', () => {
                console.log('Selected videos download cancelled, killing all yt-dlp processes')
                processes.forEach(process => process.kill('SIGTERM'))
                reject(new Error('Download cancelled'))
              })
            }

            ytdlp.stdout.on('data', (data) => {
              const output = data.toString()
              onProgress?.(output)
            })

            ytdlp.stderr.on('data', (data) => {
              stderrOutput += data.toString()
              console.error(`yt-dlp stderr: ${data}`)
            })

            ytdlp.on('close', (code) => {
              if (code === 0) {
                completedVideos++
                resolveVideo()
              } else {
                console.error(`Video ${videoId} download failed with code ${code}:`, stderrOutput)
                completedVideos++
                resolveVideo()
              }
            })

            ytdlp.on('error', (err) => {
              console.error(`Failed to start yt-dlp for video ${videoId}:`, err)
              completedVideos++
              resolveVideo()
            })
          })
        }

        onProgress?.('data: Zipping files...\n\n')
        const outputZip = fs.createWriteStream(zipFilePath)
        const archive = archiver('zip', {
          zlib: { level: 9 },
        })

        outputZip.on('close', () => {
          onProgress?.('data: Zipping complete.\n\n')
          fs.promises
            .rm(playlistSubDir, { recursive: true, force: true })
            .then(() => console.log(`Cleaned up ${playlistSubDir}`))
            .catch((err) => console.error(`Failed to clean up ${playlistSubDir}:`, err))
          resolve(zipFilePath)
        })

        archive.on('warning', (err) => {
          if (err.code === 'ENOENT') {
            console.warn('Archiver warning:', err)
          } else {
            reject(err)
          }
        })

        archive.on('error', (err) => {
          reject(err)
        })

        archive.pipe(outputZip)
        archive.directory(playlistSubDir, false)
        await archive.finalize()

      } catch (error) {
        console.error('Error in downloadSelectedVideos:', error)
        fs.promises
          .rm(playlistSubDir, { recursive: true, force: true })
          .catch((err) => console.error(`Failed cleanup after error for ${playlistSubDir}:`, err))
        reject(error)
      }
    })
  }

  private buildYtDlpArgs(
    contentIdOrUrl: string,
    formatId: string,
    outputPath: string,
    options: DownloadOptions,
    isPlaylist: boolean,
  ): string[] {
    const args = [
      '--progress',
      '--newline',
      '-f',
      formatId,
      '-o',
      outputPath,
      '--no-warnings',
      '--ignore-errors',
      '--extractor-args',
      'youtube:player_client=android,web',
    ]

    if (formatId.includes('+')) {
      args.push('--merge-output-format', 'mp4')
    } else if (options.isAudioOnly) {
      args.push('--extract-audio', '--audio-format', 'mp3')
    }

    if (options.embedThumbnail) args.push('--embed-thumbnail')
    if (options.embedChapter) args.push('--embed-chapters')
    if (options.embedMetadata) args.push('--embed-metadata')
    if (options.embedSubtitle && options.subtitleLanguage)
      args.push('--embed-subs', '--sub-langs', options.subtitleLanguage)
    args.push('--', contentIdOrUrl)

    console.log('yt-dlp args:', args.join(' '))
    return args
  }

  private parseProgress(output: string): DownloadStats | null {
    const progressRegex = /\[download\]\s+(\d+\.\d+)% of.*?(\d+\.?\d*\w*B) at\s+(.*?)\s+ETA\s+(.*)/
    const match = progressRegex.exec(output)

    if (match) {
      return {
        progress: parseFloat(match[1]),
        size: match[2],
        speed: match[3],
        eta: match[4],
      }
    }
    return null
  }

  async cleanup(): Promise<void> {
    try {
      if (fs.existsSync(this.tempDir)) {
        await fs.promises.rm(this.tempDir, { recursive: true, force: true })
        console.log(`Successfully cleaned up temporary directory: ${this.tempDir}`)
      } else {
        console.log(`Temporary directory already removed: ${this.tempDir}`)
      }
    } catch (error) {
      console.error(`Failed to delete temporary directory ${this.tempDir}:`, error)
    } finally {
      await this.ensureTempDir()
    }
  }
}

export const downloadService = new DownloadService()
