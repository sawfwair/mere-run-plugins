import { createMereProductDocsTheme } from '@mere/docs-theme'
import './plugins.css'

export default createMereProductDocsTheme({
  productName: 'mere.run plugins',
  productDomain: 'plugins.mere.run',
  docsUrl: 'https://plugins-docs.mere.run/',
  productHref: 'https://plugins.mere.run/',
  keyColor: {
    light: '#b84617',
    lightHover: '#913710',
    dark: '#f18a52',
    darkHover: '#ffad7d',
  },
  corePrefix: 'plugins',
  coreSuffix: 'mere.run',
  guideHref: '/guide/getting-started',
  architectureHref: '/operations/architecture',
  operationsHref: '/operations/provider-safety',
  referenceHref: '/reference/contracts',
  cliHref: '/reference/cli',
})
