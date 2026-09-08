const tokens=title=>new Set(String(title||'').toLowerCase().match(/[\p{L}\p{N}]+/gu)||[]);
export function groupHeadlines(articles) {
  const groups=[];
  for(const article of articles) {
    const words=tokens(article.title);
    const day=String(article.publishedAt||'').slice(0,10);
    const group=groups.find(g=>{
      if(!day||day!==g.day||article.relatedSymbol!==g.primary.relatedSymbol||words.size<4)return false;
      const a=g.words;
      // Keep numeric claims and negations separate even when other wording overlaps.
      const sensitive=set=>[...set].filter(w=>/\d/.test(w)||['not','no','never','without'].includes(w)).sort().join('|');
      if(sensitive(a)!==sensitive(words))return false;
      const shared=[...words].filter(w=>a.has(w)).length;
      return shared/(new Set([...words,...a])).size>=.85;
    });
    if(group)group.articles.push(article);
    else groups.push({primary:article,articles:[article],words,day});
  }
  return groups;
}
