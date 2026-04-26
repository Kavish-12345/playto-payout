import { useState, useEffect } from 'react'
import axios from 'axios'

const API = 'http://localhost:8000/api/v1'

function App() {
  const [merchants, setMerchants] = useState([])
  const [selectedMerchant, setSelectedMerchant] = useState(null)
  const [balance, setBalance] = useState(null)
  const [payouts, setPayouts] = useState([])
  const [amount, setAmount] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  // Load merchants on start
  useEffect(() => {
    axios.get(`${API}/merchants/`).then(res => {
      setMerchants(res.data)
      if (res.data.length > 0) {
        setSelectedMerchant(res.data[0])
      }
    })
  }, [])

  // Load balance and payouts when merchant changes
  useEffect(() => {
    if (!selectedMerchant) return
    fetchBalance()
    fetchPayouts()
  }, [selectedMerchant])

  // Poll for live updates every 5 seconds
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
        <div className="mb-6">
       <h1 className="text-5xl font-light tracking-tight">Playto Pay</h1>
<p className="text-gray-500 text-sm mt-2 uppercase tracking-wider">Merchant Payout Engine</p>
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

export default App