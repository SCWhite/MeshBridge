import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync, writeFileSync, unlinkSync, existsSync, copyFileSync, mkdirSync, readdirSync } from 'fs'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'move-build-files',
      closeBundle() {
        const distPath = path.resolve(__dirname, 'dist')
        const staticTargetPath = path.resolve(__dirname, '../static/app_noteboard')
        const templateTargetPath = path.resolve(__dirname, '../templates/app_noteboard/index.html')
        
        try {
          mkdirSync(staticTargetPath, { recursive: true })
          
          const files = readdirSync(distPath)
          let cssFile = ''
          let jsFile = ''
          
          for (const file of files) {
            const srcPath = path.join(distPath, file)
            
            if (file.endsWith('.html')) {
              let content = readFileSync(srcPath, 'utf-8')
              const timestamp = Date.now()
              
              content = content.replace(
                /<link rel="stylesheet" crossorigin href="\/([^"]+\.css)">/g,
                (match, filename) => {
                  cssFile = path.basename(filename)
                  return `<link rel="stylesheet" href="{{ url_for('static', filename='${cssFile}') }}?v=${timestamp}">`
                }
              )
              
              content = content.replace(
                /<script type="module" crossorigin src="\/([^"]+\.js)"><\/script>/g,
                (match, filename) => {
                  jsFile = path.basename(filename)
                  return `<script type="module" src="{{ url_for('static', filename='${jsFile}') }}?v=${timestamp}"></script>`
                }
              )
              
              writeFileSync(templateTargetPath, content)
              console.log('✓ Moved index.html to templates/app_noteboard/ with Flask url_for syntax')
            } else if (file.endsWith('.js') || file.endsWith('.css')) {
              const targetPath = path.join(staticTargetPath, file)
              copyFileSync(srcPath, targetPath)
              console.log(`✓ Copied ${file} to static/app_noteboard/`)
            }
          }
        } catch (e) {
          console.error('Error moving build files:', e)
        }
      }
    }
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name.endsWith('.css')) {
            return '[name][extname]';
          }
          return '[name][extname]';
        }
      },
      input: {
        main: path.resolve(__dirname, 'index.html')
      }
    }
  }
})
