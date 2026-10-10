import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <main className="page narrow">
      <h1 className="headline">Nothing to roast here.</h1>
      <p className="lede">That page doesn't exist. <Link to="/">Audit a repo instead</Link>.</p>
    </main>
  )
}
