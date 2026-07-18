import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'mere.run plugins',
  description: 'Official companion plugins for local AI production workflows with mere.run.',
  lang: 'en-US',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: false,
  sitemap: {
    hostname: 'https://plugins-docs.mere.run',
  },

  head: [
    ['meta', { name: 'theme-color', content: '#d76428' }],
    ['meta', { property: 'og:site_name', content: 'mere.run plugin docs' }],
    ['meta', { property: 'og:image', content: 'https://plugins.mere.run/og.png' }],
  ],

  themeConfig: {
    siteTitle: 'mere.run / plugins',
    nav: [
      { text: 'Guide', link: '/guide/introduction', activeMatch: '/guide/' },
      { text: 'Plugins', link: '/plugins/', activeMatch: '/plugins/' },
      {
        text: 'Reference',
        activeMatch: '/reference/',
        items: [
          { text: 'CLI lifecycle', link: '/reference/cli' },
          { text: 'Catalog', link: '/reference/catalog' },
          { text: 'Contracts', link: '/reference/contracts' },
          { text: 'Run manifest', link: '/reference/run-manifest' },
          { text: 'Environment', link: '/reference/environment' },
          { text: 'Exit codes', link: '/reference/exit-codes' },
        ],
      },
      {
        text: 'Operations',
        activeMatch: '/operations/',
        items: [
          { text: 'Architecture', link: '/operations/architecture' },
          { text: 'Security', link: '/operations/security' },
          { text: 'Provider safety', link: '/operations/provider-safety' },
          { text: 'Development', link: '/operations/development' },
          { text: 'Testing', link: '/operations/testing' },
          { text: 'Releasing', link: '/operations/releasing' },
          { text: 'Troubleshooting', link: '/operations/troubleshooting' },
        ],
      },
      { text: 'plugins.mere.run', link: 'https://plugins.mere.run/' },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Start here',
          collapsed: false,
          items: [
            { text: 'Introduction', link: '/guide/introduction' },
            { text: 'Getting started', link: '/guide/getting-started' },
            { text: 'Choose a plugin', link: '/guide/choosing-a-plugin' },
            { text: 'Core concepts', link: '/guide/core-concepts' },
            { text: 'Lifecycle', link: '/guide/lifecycle' },
            { text: 'Artifacts and runs', link: '/guide/artifacts-and-runs' },
            { text: 'Graph providers', link: '/guide/graph-providers' },
          ],
        },
        {
          text: 'Production paths',
          collapsed: false,
          items: [
            { text: 'Build a VFX shot', link: '/guide/vfx-shot' },
            { text: 'Play a realtime show', link: '/guide/realtime-performance' },
            { text: 'Train a LoRA on RunPod', link: '/guide/runpod-lora' },
            { text: 'Publish to ShotGrid', link: '/guide/shotgrid-publish' },
            { text: 'Keep workflows private', link: '/guide/private-workflows' },
          ],
        },
      ],
      '/plugins/': [
        {
          text: 'Plugin catalog',
          collapsed: false,
          items: [
            { text: 'All plugins', link: '/plugins/' },
            { text: 'Face Tools', link: '/plugins/face-tools' },
            { text: 'VFX Tools', link: '/plugins/vfx-tools' },
            { text: 'Perform', link: '/plugins/perform' },
            { text: 'Image Tools', link: '/plugins/image-tools' },
            { text: 'Animatic Tools', link: '/plugins/animatic-tools' },
            { text: 'ShotGrid Tools', link: '/plugins/shotgrid-tools' },
            { text: 'RunPod Runner', link: '/plugins/runpod' },
            { text: 'Document Tools', link: '/plugins/document-tools' },
            { text: 'Media Scrub', link: '/plugins/media-scrub' },
            { text: 'Dataset Tools', link: '/plugins/dataset-tools' },
            { text: 'Transcript Tools', link: '/plugins/transcript-tools' },
            { text: 'Image Compose', link: '/plugins/image-compose' },
            { text: 'Batch Runner', link: '/plugins/batch-runner' },
          ],
        },
        {
          text: 'Plugin authors',
          collapsed: false,
          items: [
            { text: 'Plugin contract', link: '/plugins/contract' },
            { text: 'Security rules', link: '/plugins/security' },
            { text: 'Workflow tools package', link: '/plugins/workflow-tools' },
          ],
        },
      ],
      '/reference/': [
        {
          text: 'Reference',
          collapsed: false,
          items: [
            { text: 'CLI lifecycle', link: '/reference/cli' },
            { text: 'Catalog', link: '/reference/catalog' },
            { text: 'Contracts', link: '/reference/contracts' },
            { text: 'Run manifest', link: '/reference/run-manifest' },
            { text: 'Recipes', link: '/reference/recipes' },
            { text: 'Environment', link: '/reference/environment' },
            { text: 'Exit codes', link: '/reference/exit-codes' },
            { text: 'Coverage map', link: '/reference/coverage' },
          ],
        },
      ],
      '/operations/': [
        {
          text: 'Operate and contribute',
          collapsed: false,
          items: [
            { text: 'Architecture', link: '/operations/architecture' },
            { text: 'Security', link: '/operations/security' },
            { text: 'Provider safety', link: '/operations/provider-safety' },
            { text: 'Development', link: '/operations/development' },
            { text: 'Testing', link: '/operations/testing' },
            { text: 'Releasing', link: '/operations/releasing' },
            { text: 'Troubleshooting', link: '/operations/troubleshooting' },
          ],
        },
      ],
    },

    outline: { level: [2, 3], label: 'On this page' },
    search: { provider: 'local' },
    docFooter: { prev: true, next: true },
    editLink: {
      pattern: 'https://github.com/sawfwair/mere-run-plugins/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    socialLinks: [{ icon: 'github', link: 'https://github.com/sawfwair/mere-run-plugins' }],
    footer: {
      message: 'Official companion plugins for the local mere.run runtime.',
      copyright: 'MIT licensed · Sawfwair',
    },
  },
})
