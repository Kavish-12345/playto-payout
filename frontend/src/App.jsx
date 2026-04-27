import { useState, useEffect } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

function HomePage({ onEnter }) {
  return (
    <div className="min-h-screen bg-black text-white flex flex-col">
  

      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="mb-6">
      
          <h1 className="text-6xl md:text-8xl font-light tracking-tight leading-none mb-4">
            Playto
            <br />
            <span className="text-gray-600">Pay</span>
          </h1>

          <p className="text-gray-500 text-sm uppercase tracking-wider mt-6 mb-2">
            Merchant Payout Engine
          </p>
          <p className="text-gray-600 text-sm max-w-sm mx-auto leading-relaxed">
            Manage payouts, track balances, and monitor transactions across all your merchants in real time.
          </p>
        </div>

        <button
          onClick={onEnter}
          className="group border border-white bg-white text-black px-10 py-4 text-sm uppercase tracking-widest font-medium hover:bg-black hover:text-white transition-all duration-300 flex items-center gap-3"
        >
          Enter Dashboard
          <span className="group-hover:translate-x-1 transition-transform duration-300">→</span>
        </button>
      </div>


    </div>
  )
}

function Dashboard({ onBack }) {
  const [merchants, setMerchants] = useState([])
  const [selectedMerchant, setSelectedMerchant] = useState(null)
  const [balance, setBalance] = useState(null)
  const [payouts, setPayouts] = useState([])
  const [amount, setAmount] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    axios.get(`${API}/merchants/`).then(res => {
      setMerchants(res.data)
      if (res.data.length > 0) {
        setSelectedMerchant(res.data[0])
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedMerchant) return
    fetchBalance()
    fetchPayouts()
  }, [selectedMerchant])

  useEffect(() => {
    if (!selectedMerchant) return
    const interval = setInterval(() => {
      fetchBalance()
      fetchPayouts()
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedMerchant])

  const fetchBalance = () => {
    axios.get(`${API}/merchants/${selectedMerchant.id}/balance/`)
      .then(res => setBalance(res.data))
  }

  const fetchPayouts = () => {
    axios.get(`${API}/payouts/?merchant_id=${selectedMerchant.id}`)
      .then(res => setPayouts(res.data))
  }

  const requestPayout = async () => {
    if (!amount || amount <= 0) {
      setMessage('Enter a valid amount')
      return
    }

    const amountPaise = parseInt(amount) * 100

    if (amountPaise > balance?.available_balance_paise) {
      setMessage('Insufficient balance')
      return
    }

    setLoading(true)
    setMessage('')

    try {
      const key = `key-${Date.now()}-${Math.random()}`
      await axios.post(`${API}/payouts/`, {
        merchant_id: selectedMerchant.id,
        amount_paise: amountPaise,
        bank_account_id: selectedMerchant.id
      }, {
        headers: { 'Idempotency-Key': key }
      })
      setMessage('Payout requested successfully')
      setAmount('')
      fetchBalance()
      fetchPayouts()
    } catch (err) {
      setMessage(err.response?.data?.error || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const formatPaise = (paise) => {
    if (!paise) return '₹0'
    return `₹${(paise / 100).toLocaleString('en-IN')}`
  }

  const statusColor = (status) => {
    switch (status) {
      case 'COMPLETED': return 'text-green-600 bg-green-50'
      case 'FAILED': return 'text-red-600 bg-red-50'
      case 'PROCESSING': return 'text-yellow-600 bg-yellow-50'
      default: return 'text-blue-600 bg-blue-50'
    }
  }

  return (
    <div className="min-h-screen bg-black text-white p-6">
      <div className="max-w-4xl mx-auto">

        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-5xl font-light tracking-tight">Playto Pay</h1>
            <p className="text-gray-500 text-sm mt-2 uppercase tracking-wider">Merchant Payout Engine</p>
          </div>
          <button
            onClick={onBack}
            className="flex items-center gap-2 border border-gray-800 px-4 py-2 text-xs uppercase tracking-wider text-gray-400 hover:border-gray-600 hover:text-white transition-all duration-200 mt-1"
          >
            <span>←</span>
            Back
          </button>
        </div>

        {/* Merchant Selector */}
        <div className="border border-gray-800 bg-neutral-950 p-4 mb-4">
          <label className="text-xs uppercase tracking-wider text-gray-500">Select Merchant</label>
          <select
            className="mt-1 block w-full bg-black border border-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:border-white"
            onChange={e => {
              const m = merchants.find(m => m.id === parseInt(e.target.value))
              setSelectedMerchant(m)
            }}
            value={selectedMerchant?.id || ''}
          >
            {merchants.map(m => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>

        {/* Balance Cards */}
        {balance && (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="border border-gray-800 bg-neutral-950 p-4">
              <p className="text-xs uppercase tracking-wider text-gray-500">Available Balance</p>
              <p className="text-2xl font-light text-white">
                {formatPaise(balance.available_balance_paise)}
              </p>
            </div>
            <div className="border border-gray-800 bg-neutral-950 p-4">
              <p className="text-xs uppercase tracking-wider text-gray-500">Held Balance</p>
              <p className="text-2xl font-light text-yellow-400">
                {formatPaise(balance.held_balance_paise)}
              </p>
            </div>
          </div>
        )}

        {/* Payout Form */}
        <div className="border border-gray-800 bg-neutral-950 p-4 mb-4">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3 font-medium">Request Payout</h2>
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Amount in ₹"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              className="flex-1 bg-black border border-gray-800 px-4 py-3 text-sm text-white focus:outline-none focus:border-white transition-colors"
            />
            <button
              onClick={requestPayout}
              disabled={loading}
              className="border border-white bg-white text-black px-6 py-3 text-sm uppercase tracking-wider font-medium hover:bg-black hover:text-white transition-all duration-300 disabled:opacity-50"
            >
              {loading ? 'Processing...' : 'Request Payout'}
            </button>
          </div>
          {message && (
            <p className={`mt-2 text-sm ${message.includes('success') ? 'text-green-600' : 'text-red-600'}`}>
              {message}
            </p>
          )}
        </div>

        {/* Recent Transactions */}
        {balance?.recent_transactions?.length > 0 && (
          <div className="border border-gray-800 bg-neutral-950 p-4 mb-4">
            <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3 font-medium">Recent Transactions</h2>
            <div className="space-y-2">
              {balance.recent_transactions.map(t => (
                <div key={t.id} className="flex justify-between items-center text-sm">
                  <span className="text-gray-400">{t.description}</span>
                  <span className={t.amount_paise > 0 ? 'text-green-600' : 'text-red-600'}>
                    {t.amount_paise > 0 ? '+' : ''}{formatPaise(t.amount_paise)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Payout History */}
        <div className="border border-gray-800 bg-neutral-950 p-4">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3 font-medium">
            Payout History
            <span className="ml-2 text-xs text-gray-400">(auto-refreshes every 5s)</span>
          </h2>
          {payouts.length === 0 ? (
            <p className="text-sm text-gray-400">No payouts yet</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-600 border-b border-gray-800 uppercase text-xs tracking-wider">
                  <th className="pb-2">ID</th>
                  <th className="pb-2">Amount</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {payouts.map(p => (
                  <tr key={p.id} className="border-b border-gray-900 last:border-0">
                    <td className="py-2 text-gray-500">#{p.id}</td>
                    <td className="py-2">{formatPaise(p.amount_paise)}</td>
                    <td className="py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(p.status)}`}>
                        {p.status}
                      </span>
                    </td>
                    <td className="py-2 text-gray-400">
                      {new Date(p.created_at).toLocaleString('en-IN')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

      </div>
    </div>
  )
}

function App() {
  const [page, setPage] = useState('home')

  if (page === 'dashboard') {
    return <Dashboard onBack={() => setPage('home')} />
  }

  return <HomePage onEnter={() => setPage('dashboard')} />
}

export default App