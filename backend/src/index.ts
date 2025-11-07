import 'dotenv/config'
import express from 'express'
import cors from 'cors'

const app = express()
app.use(cors({ origin: process.env.ALLOWED_ORIGINS?.split(',') || true }))
app.use(express.json())

app.get('/', (_req, res) => res.json({ ok: true, service: 'aurora-backend' }))

const port = Number(process.env.PORT || 8080)
app.listen(port, () => console.log(`Backend listening on :${port}`))
