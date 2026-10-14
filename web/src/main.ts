// 应用入口:挂载 + 全局样式(与原型一致的 token 体系)
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
