-- Pandoc filter for the LNCS Word build: map the marker environments written by
-- build_lncs.py onto LNCS paragraph styles, and number figure and table captions
-- the LNCS way ("Fig. 1." and "Table 1.", label in bold).
local style = {
  papertitle = "papertitle", author = "author", address = "address", email = "address",
  abstractblock = "abstract", keywords = "keywords", acknowledgments = "p1a",
  declaration = "bulletitem", contribution = "p1a", algline = "programcode", algcaption = "p1a",
}

local fig_n, tab_n = 0, 0

local function prefix_caption(caption, label)
  local blocks = caption.long
  if #blocks == 0 then
    blocks = { pandoc.Plain({}) }
  end
  local first = blocks[1]
  local inl = { pandoc.Strong({ pandoc.Str(label) }), pandoc.Space() }
  for _, x in ipairs(first.content) do inl[#inl + 1] = x end
  first.content = inl
  caption.long = blocks
  return caption
end

function Div(el)
  for cls, s in pairs(style) do
    if el.classes:includes(cls) then
      el.attributes["custom-style"] = s
      el.classes = {}
      return el
    end
  end
  if el.classes:includes("algorithmblock") then
    return el.content
  end
end

function Figure(el)
  fig_n = fig_n + 1
  el.caption = prefix_caption(el.caption, "Fig. " .. fig_n .. ".")
  if #el.content <= 1 then
    return el
  end
  -- several image rows: pandoc would lay them out as small subfigures, so emit the
  -- rows as centred image paragraphs followed by an LNCS caption paragraph
  local rows = {}
  for _, b in ipairs(el.content) do
    local imgs = {}
    b:walk({ Image = function(im) imgs[#imgs + 1] = im end })
    if #imgs > 0 then
      local inl = {}
      for k, im in ipairs(imgs) do
        if k > 1 then inl[#inl + 1] = pandoc.Space() end
        inl[#inl + 1] = im
      end
      rows[#rows + 1] = pandoc.Para(inl)
    end
  end
  local cap = pandoc.utils.blocks_to_inlines(el.caption.long)
  return {
    pandoc.Div(rows, { ["custom-style"] = "image" }),
    pandoc.Div({ pandoc.Para(cap) }, { ["custom-style"] = "figurecaption" }),
  }
end

function Table(el)
  tab_n = tab_n + 1
  if #el.caption.long > 0 then
    el.caption = prefix_caption(el.caption, "Table " .. tab_n .. ".")
  end
  return el
end
